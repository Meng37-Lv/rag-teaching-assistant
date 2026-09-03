from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from scripts.build_vector_db import DEFAULT_MODEL, build_index, encode_chunks, save_chunks_mapping, save_faiss_index
from scripts.split_text import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, split_text
from src.course_data import CourseStore, get_course_store
from src.material_parser import MaterialParseError, SUPPORTED_MATERIAL_TYPES, parse_material_file
from src.retriever import CourseRetriever, RetrievedChunk


MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILES = 10
ALLOWED_SUFFIXES = set(SUPPORTED_MATERIAL_TYPES)


class MaterialInfo(BaseModel):
    id: str
    filename: str
    size: int
    uploaded_at: str


class BuildStatus(BaseModel):
    course_id: str
    status: str
    error: str | None = None


class CourseMaterialService:
    def __init__(self, course_store: CourseStore, root: Path | None = None) -> None:
        self.course_store = course_store
        self.root = root or Path(__file__).resolve().parents[1] / "storage" / "courses"
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._errors: dict[str, str] = {}

    def _course_dir(self, course_id: str) -> Path:
        return self.root / course_id

    def _lock(self, course_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(course_id, threading.Lock())

    def _require_course(self, course_id: str):
        course = self.course_store.get(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="课程不存在")
        return course

    def list_materials(self, course_id: str) -> list[MaterialInfo]:
        self._require_course(course_id)
        directory = self._course_dir(course_id) / "source_files"
        if not directory.exists():
            return []
        result: list[MaterialInfo] = []
        for path in sorted(directory.iterdir()):
            if path.is_file():
                material_id, _, original_name = path.name.partition("__")
                result.append(MaterialInfo(id=material_id or path.stem, filename=original_name or path.name, size=path.stat().st_size, uploaded_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()))
        return result

    def upload(self, course_id: str, upload: UploadFile) -> MaterialInfo:
        course = self._require_course(course_id)
        if course_id == "default":
            raise HTTPException(status_code=400, detail="预置课程资料不可修改，如需新资料请创建课程")
        if course.status == "building":
            raise HTTPException(status_code=409, detail="课程正在构建，暂不能修改资料")
        if course.status not in {"draft", "failed", "ready"}:
            raise HTTPException(status_code=400, detail="当前课程状态不允许上传资料")
        filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持PPTX、DOCX、MD、TXT文件")
        content = upload.file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="单个文件不能超过100MB")
        directory = self._course_dir(course_id) / "source_files"
        if len(self.list_materials(course_id)) >= MAX_FILES:
            raise HTTPException(status_code=400, detail="每课程最多上传10个文件")
        directory.mkdir(parents=True, exist_ok=True)
        material_id = uuid4().hex
        path = directory / f"{material_id}__{filename}"
        path.write_bytes(content)
        if course.status == "ready":
            self.course_store.set_status(course_id, "draft")
        return MaterialInfo(id=material_id, filename=filename, size=len(content), uploaded_at=datetime.now(timezone.utc).isoformat())

    def delete(self, course_id: str, material_id: str) -> None:
        course = self._require_course(course_id)
        if course_id == "default":
            raise HTTPException(status_code=400, detail="预置课程资料不可修改，如需新资料请创建课程")
        if course.status == "building":
            raise HTTPException(status_code=409, detail="课程正在构建，暂不能修改资料")
        path = next((p for p in (self._course_dir(course_id) / "source_files").glob(f"{material_id}__*") if p.is_file()), None)
        if path is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        path.unlink()
        if course.status == "ready":
            self.course_store.set_status(course_id, "draft")

    def build(self, course_id: str) -> BuildStatus:
        course = self._require_course(course_id)
        if course_id == "default":
            raise HTTPException(status_code=400, detail="预置课程资料不可修改，如需新资料请创建课程")
        if course.status == "building" or not self._lock(course_id).acquire(blocking=False):
            raise HTTPException(status_code=409, detail="课程正在构建，禁止重复构建")
        try:
            files = [item for item in (self._course_dir(course_id) / "source_files").iterdir() if item.is_file()] if (self._course_dir(course_id) / "source_files").exists() else []
            if not files:
                self.course_store.set_status(course_id, "failed")
                self._errors[course_id] = "构建前至少需要一份资料"
                return BuildStatus(course_id=course_id, status="failed", error=self._errors[course_id])
            extracted_dir = self._course_dir(course_id) / "extracted"
            vector_dir = self._course_dir(course_id) / "vector_db"
            extracted_dir.mkdir(parents=True, exist_ok=True)
            self.course_store.set_status(course_id, "building")
            chunks: list[dict[str, object]] = []
            failures: list[str] = []
            for path in files:
                try:
                    parsed = parse_material_file(path)
                    if not parsed.extracted_text.strip():
                        failures.append(f"{path.name}：未提取到有效文本")
                        continue
                    (extracted_dir / f"{path.stem}.txt").write_text(parsed.extracted_text, encoding="utf-8")
                    for chunk in split_text(parsed.extracted_text, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP):
                        chunk["source_file"] = path.name
                        chunks.append(chunk)
                except (MaterialParseError, Exception) as error:
                    failures.append(f"{path.name}：{error}")
            if not chunks:
                raise ValueError("没有资料提取出有效文本或索引")
            vector_dir.mkdir(parents=True, exist_ok=True)
            index = build_index(encode_chunks(chunks, DEFAULT_MODEL))
            save_faiss_index(index, vector_dir / "course.index")
            save_chunks_mapping(chunks, vector_dir / "chunks.pkl")
            (vector_dir / "source_mapping.json").write_text(
                json.dumps({str(i): {"source_file": c.get("source_file"), "page": c.get("page")} for i, c in enumerate(chunks)}, ensure_ascii=False),
                encoding="utf-8",
            )
            self._errors.pop(course_id, None)
            self.course_store.set_status(course_id, "ready")
            return BuildStatus(course_id=course_id, status="ready", error=("；".join(failures) if failures else None))
        except Exception as error:
            self.course_store.set_status(course_id, "failed")
            self._errors[course_id] = f"知识库构建失败：{error}"
            return BuildStatus(course_id=course_id, status="failed", error=self._errors[course_id])
        finally:
            self._lock(course_id).release()

    def status(self, course_id: str) -> BuildStatus:
        course = self._require_course(course_id)
        return BuildStatus(course_id=course_id, status=course.status, error=self._errors.get(course_id))

class CourseSourceMapper:
    """Source formatter for an isolated course index."""

    def __init__(self, mapping_path: Path) -> None:
        self.mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
        self.valid_pages = {int(value["page"]) for value in self.mapping.values() if isinstance(value, dict) and isinstance(value.get("page"), int)}

    def format_chunk_source(self, chunk: RetrievedChunk) -> str:
        entry = self.mapping.get(str(chunk.chunk_id), {})
        source_file = entry.get("source_file", "课程资料") if isinstance(entry, dict) else entry
        if chunk.page is not None:
            return f"{source_file}，第{chunk.page}页"
        return f"{source_file}，课程资料片段{chunk.chunk_id + 1}"

    def sanitize_value(self, value):
        if isinstance(value, str):
            if not self.valid_pages:
                return value
            return re.sub(
                r"第(\d+)页",
                lambda match: match.group(0) if int(match.group(1)) in self.valid_pages else "课程页码引用已移除（该课程来源映射不可用）",
                value,
            )
        if isinstance(value, list):
            return [self.sanitize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.sanitize_value(item) for key, item in value.items()}
        return value


def load_course_retriever(course_id: str, root: Path | None = None) -> tuple[CourseRetriever, CourseSourceMapper]:
    base = (root or Path(__file__).resolve().parents[1] / "storage" / "courses") / course_id
    vector_dir = base / "vector_db"
    retriever = CourseRetriever(vector_dir / "course.index", vector_dir / "chunks.pkl", DEFAULT_MODEL)
    return retriever, CourseSourceMapper(vector_dir / "source_mapping.json")


_service: CourseMaterialService | None = None


def get_material_service(store: CourseStore = Depends(get_course_store)) -> CourseMaterialService:
    global _service
    if _service is None or _service.course_store is not store:
        _service = CourseMaterialService(store)
    return _service


router = APIRouter(prefix="/api/courses/{course_id}/materials", tags=["course-materials"])


@router.post("", response_model=MaterialInfo, status_code=201)
def upload_material(course_id: str, file: UploadFile = File(...), service: CourseMaterialService = Depends(get_material_service)) -> MaterialInfo:
    return service.upload(course_id, file)


@router.get("", response_model=list[MaterialInfo])
def list_materials(course_id: str, service: CourseMaterialService = Depends(get_material_service)) -> list[MaterialInfo]:
    return service.list_materials(course_id)


@router.delete("/{material_id}", status_code=204)
def delete_material(course_id: str, material_id: str, service: CourseMaterialService = Depends(get_material_service)) -> None:
    service.delete(course_id, material_id)


@router.post("/build", response_model=BuildStatus, status_code=202)
def build_materials(course_id: str, service: CourseMaterialService = Depends(get_material_service)) -> BuildStatus:
    return service.build(course_id)


@router.get("/build-status", response_model=BuildStatus)
def build_status(course_id: str, service: CourseMaterialService = Depends(get_material_service)) -> BuildStatus:
    return service.status(course_id)

