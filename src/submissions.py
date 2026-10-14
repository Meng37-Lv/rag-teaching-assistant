from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.auth import get_accounts
from src.data_paths import get_submission_preview_dir, storage_root
from src.material_parser import MaterialParseError, ParsedMaterial, MaterialSegment, parse_material_file
from src.config import load_preview_settings, load_settings
from src.preview_converter import PreviewConversionError, convert_to_pdf
from src.report_question_service import ReportQuestionOutputError, ReportQuestionService
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError


SUPPORTED_TYPES = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".txt": "txt", ".md": "md"}
MAX_FILE_BYTES = int(os.getenv("SUBMISSION_MAX_FILE_BYTES", str(20 * 1024 * 1024)))
MAX_TOTAL_BYTES = int(os.getenv("SUBMISSION_MAX_TOTAL_BYTES", str(50 * 1024 * 1024)))
MAX_FILES = int(os.getenv("SUBMISSION_MAX_FILES", "10"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _db(request: Request) -> Path:
    return get_accounts(request).db_path


def _session(request: Request, session_id: str) -> sqlite3.Row:
    connection = _connect(_db(request))
    row = connection.execute(
        """SELECT s.session_id, s.class_id, s.status, c.course_id, c.name AS class_name
           FROM classroom_sessions s JOIN classes c ON c.class_id=s.class_id
           WHERE s.session_id=?""", (session_id,)
    ).fetchone()
    connection.close()
    if row is None:
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "课堂不存在。"})
    return row


def _teacher_session(request: Request, session_id: str, *, require_active: bool = False) -> sqlite3.Row:
    row = _session(request, session_id)
    if not get_accounts(request).owns(request.state.account["account_id"], row["course_id"]):
        raise HTTPException(404, detail={"code": "FORBIDDEN", "message": "课程不存在或无权访问。"})
    if require_active and row["status"] != "active":
        raise HTTPException(409, detail={"code": "CLASSROOM_ENDED", "message": "课堂未进行中，不能执行此操作。"})
    return row


def _student_session(request: Request, session_id: str, *, require_active: bool = True) -> sqlite3.Row:
    token = request.headers.get("X-Student-Session", "").strip()
    if not token:
        raise HTTPException(401, detail={"code": "STUDENT_TOKEN_INVALID", "message": "学生令牌无效。"})
    connection = _connect(_db(request))
    row = connection.execute(
        """SELECT s.session_id, s.status AS session_status, cs.session_student_id,
                  cs.student_id, cs.requested_name, st.name, st.student_no
           FROM classroom_students cs
           JOIN classroom_sessions s ON s.session_id=cs.session_id
           LEFT JOIN class_students st ON st.student_id=cs.student_id
           WHERE cs.session_id=? AND cs.student_token_hash=? AND cs.status='confirmed'""",
        (session_id, _hash(token)),
    ).fetchone()
    connection.close()
    if row is None:
        raise HTTPException(403, detail={"code": "STUDENT_TOKEN_INVALID", "message": "学生令牌无效或尚未确认。"})
    if require_active and row["session_status"] != "active":
        raise HTTPException(409, detail={"code": "CLASSROOM_ENDED", "message": "课堂未进行中，学生不能提交材料。"})
    return row


def _safe_filename(filename: str) -> str:
    name = Path((filename or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f<>:\"/|?*]", "_", name).strip()
    if not name:
        raise HTTPException(400, detail={"code": "INVALID_FILENAME", "message": "文件名不能为空。"})
    return name[:255]


def _preview_type(file_type: str) -> str:
    return {"pptx": "pptx", "docx": "docx", "md": "markdown", "pdf": "pdf", "txt": "text"}[file_type]


def _extract_summary(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return data.decode("utf-8-sig", errors="replace")[:4000]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    try:
        parsed = parse_material_file(temporary_path)
        return parsed.extracted_text[:4000]
    except (MaterialParseError, OSError) as error:
        raise HTTPException(400, detail={"code": "FILE_PARSE_FAILED", "message": f"文件“{filename}”损坏或无法解析，未保存提交。"}) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _student_info(connection: sqlite3.Connection, session_student_id: str) -> dict[str, str | None]:
    row = connection.execute(
        """SELECT cs.requested_name, st.name, st.student_no
           FROM classroom_students cs LEFT JOIN class_students st ON st.student_id=cs.student_id
           WHERE cs.session_student_id=?""", (session_student_id,)
    ).fetchone()
    if row is None:
        return {"name": None, "student_no": None}
    return {"name": row["name"] or row["requested_name"], "student_no": row["student_no"]}


def _file_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"], "file_id": row["id"], "filename": row["filename"],
        "file_type": row["file_type"], "size_bytes": row["size_bytes"],
        "size": row["size_bytes"], "chunk_summary": row["chunk_summary"],
        "preview_type": row["preview_type"], "uploaded_at": row["created_at"],
    }


def _submission_payload(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    files = connection.execute("SELECT * FROM submission_files WHERE submission_id=? ORDER BY created_at, id", (row["id"],)).fetchall()
    return {
        "submission_id": row["id"], "id": row["id"], "session_id": row["session_id"],
        "round_id": row["round_id"] if "round_id" in row.keys() else None,
        "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "student": _student_info(connection, row["session_student_id"]),
        "files": [_file_payload(item) for item in files],
    }


def _authorize_round_submission(connection: sqlite3.Connection, request: Request, row: sqlite3.Row, *, require_current: bool = True) -> sqlite3.Row | None:
    """Validate the immutable round/student binding for a submission file."""
    round_id = row["round_id"] if "round_id" in row.keys() else None
    if not round_id:
        return None
    round_row = connection.execute(
        """SELECT r.*, cc.state AS claim_state, cc.session_student_id AS claim_student_id
           FROM collaboration_rounds r JOIN collaboration_claims cc ON cc.round_id=r.round_id
           WHERE r.round_id=? AND r.session_id=? AND r.class_id=(SELECT class_id FROM classroom_sessions WHERE session_id=?)
             AND cc.session_student_id=? AND cc.state IN ('accepted','completed')
           ORDER BY cc.updated_at DESC LIMIT 1""",
        (round_id, row["session_id"], row["session_id"], row["session_student_id"]),
    ).fetchone()
    if round_row is None or (require_current and round_row["state"] != "open"):
        raise HTTPException(409, detail={"code": "COLLABORATION_ROUND_CLOSED", "message": "当前汇报协作轮次已关闭。"})
    return round_row


router = APIRouter(tags=["submissions"])


@router.post("/api/sessions/{session_id}/submissions")
async def create_submission(
    session_id: str,
    request: Request,
    files: Annotated[list[UploadFile] | None, File(description="支持 PDF/PPTX/DOCX/TXT/MD")]=None,
    round_id: str | None = Form(default=None),
) -> dict[str, object]:
    student = _student_session(request, session_id, require_active=True)
    uploads = files or []
    if not uploads:
        raise HTTPException(400, detail={"code": "NO_FILES", "message": "请至少选择一个汇报材料文件。"})
    if len(uploads) > MAX_FILES:
        raise HTTPException(400, detail={"code": "FILE_COUNT_EXCEEDED", "message": f"单次最多提交{MAX_FILES}个文件。"})

    prepared: list[tuple[str, str, bytes, str]] = []
    total = 0
    for upload in uploads:
        filename = _safe_filename(upload.filename or "")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_TYPES:
            raise HTTPException(400, detail={"code": "FILE_TYPE_UNSUPPORTED", "message": f"文件“{filename}”类型不支持，仅支持 PDF、PPTX、DOCX、TXT、MD。"})
        data = await upload.read(MAX_FILE_BYTES + 1)
        await upload.close()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, detail={"code": "FILE_SIZE_EXCEEDED", "message": f"文件“{filename}”超过20MB限制。"})
        if not data:
            raise HTTPException(400, detail={"code": "EMPTY_FILE", "message": f"文件“{filename}”不能为空。"})
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(413, detail={"code": "TOTAL_SIZE_EXCEEDED", "message": "本次提交文件合计不能超过50MB。"})
        prepared.append((filename, suffix[1:], data, _extract_summary(data, filename)))

    submission_id = str(uuid4())
    created_at = _now()
    target_dir = (storage_root() / "submissions" / session_id / submission_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=False)
    connection = _connect(_db(request))
    if round_id:
        valid=connection.execute("SELECT 1 FROM collaboration_rounds r JOIN collaboration_claims cc ON cc.round_id=r.round_id WHERE r.round_id=? AND r.session_id=? AND r.class_id=(SELECT class_id FROM classroom_sessions WHERE session_id=?) AND r.feature_type='presentation_questions' AND cc.session_student_id=? AND cc.state='accepted' AND r.state='open'",(round_id,session_id,session_id,student['session_student_id'])).fetchone()
        if not valid:
            connection.close(); shutil.rmtree(target_dir, ignore_errors=True); raise HTTPException(409, detail={"code":"COLLABORATION_NOT_ACCEPTED","message":"当前协作轮次尚未接受或已结束。"})
    try:
        with connection:
            connection.execute(
                "INSERT INTO submissions(id,session_id,session_student_id,student_session_token_hash,status,created_at,updated_at,round_id) VALUES (?,?,?,?,?,?,?,?)",
                (submission_id, session_id, student["session_student_id"], _hash(request.headers["X-Student-Session"]), "submitted", created_at, created_at, round_id),
            )
            for filename, file_type, data, summary in prepared:
                file_id = str(uuid4())
                stored = target_dir / f"{file_id}{Path(filename).suffix.lower()}"
                stored.write_bytes(data)
                connection.execute(
                    "INSERT INTO submission_files(id,submission_id,filename,file_type,size_bytes,storage_path,chunk_summary,preview_type,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (file_id, submission_id, filename, file_type, len(data), str(stored), summary, _preview_type(file_type), created_at),
                )
        row = connection.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        return _submission_payload(connection, row)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    finally:
        connection.close()


@router.get("/api/sessions/{session_id}/submissions")
def list_submissions(
    session_id: str,
    request: Request,
    student_name: str | None = Query(default=None),
    student_no: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    round_id: str | None = Query(default=None),
) -> dict[str, object]:
    student_token = request.headers.get("X-Student-Session")
    if student_token:
        student = _student_session(request, session_id, require_active=False)
        student_id = student["session_student_id"]
    else:
        _teacher_session(request, session_id)
        student_id = None
    connection = _connect(_db(request))
    where = ["s.session_id=?"]
    params: list[object] = [session_id]
    if student_id:
        where.append("s.session_student_id=?"); params.append(student_id)
    if student_name:
        where.append("COALESCE(st.name,cs.requested_name) LIKE ?"); params.append(f"%{student_name.strip()}%")
    if student_no:
        where.append("st.student_no LIKE ?"); params.append(f"%{student_no.strip()}%")
    if round_id:
        where.append("s.round_id=?"); params.append(round_id)
        where.append("EXISTS (SELECT 1 FROM collaboration_rounds cr JOIN collaboration_claims ccl ON ccl.round_id=cr.round_id WHERE cr.round_id=s.round_id AND cr.session_id=s.session_id AND cr.state='open' AND ccl.session_student_id=s.session_student_id AND ccl.state IN ('accepted','completed'))")
    elif not student_id:
        where.append("(s.round_id IS NULL OR EXISTS (SELECT 1 FROM collaboration_rounds cr JOIN collaboration_claims ccl ON ccl.round_id=cr.round_id WHERE cr.round_id=s.round_id AND cr.session_id=s.session_id AND cr.state='open' AND ccl.session_student_id=s.session_student_id AND ccl.state IN ('accepted','completed')))")
    where_sql = " AND ".join(where)
    order = "ASC" if sort == "asc" else "DESC"
    total = connection.execute(
        f"""SELECT COUNT(*) FROM submissions s JOIN classroom_students cs ON cs.session_student_id=s.session_student_id
             LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE {where_sql}""", params,
    ).fetchone()[0]
    rows = connection.execute(
        f"""SELECT s.* FROM submissions s JOIN classroom_students cs ON cs.session_student_id=s.session_student_id
             LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE {where_sql}
             ORDER BY s.created_at {order}, s.id {order} LIMIT ? OFFSET ?""", [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    payload = [_submission_payload(connection, row) for row in rows]
    connection.close()
    return {"items": payload, "submissions": payload, "total": total, "page": page, "page_size": page_size}


@router.get("/api/submissions/{submission_id}")
def get_submission(submission_id: str, request: Request) -> dict[str, object]:
    connection = _connect(_db(request))
    row = connection.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
    if row is None:
        connection.close(); raise HTTPException(404, detail={"code": "SUBMISSION_NOT_FOUND", "message": "提交记录不存在。"})
    if request.headers.get("X-Student-Session"):
        student = _student_session(request, row["session_id"], require_active=False)
        if student["session_student_id"] != row["session_student_id"]:
            connection.close(); raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "无权查看该提交。"})
    else:
        _teacher_session(request, row["session_id"])
    _authorize_round_submission(connection, request, row)
    payload = _submission_payload(connection, row)
    connection.close()
    return payload


def _file_and_submission(request: Request, file_id: str) -> tuple[sqlite3.Connection, sqlite3.Row, sqlite3.Row]:
    connection = _connect(_db(request))
    row = connection.execute("SELECT f.*,s.id AS submission_id,s.session_id,s.session_student_id,s.status,s.round_id FROM submission_files f JOIN submissions s ON s.id=f.submission_id WHERE f.id=?", (file_id,)).fetchone()
    if row is None:
        connection.close(); raise HTTPException(404, detail={"code": "FILE_NOT_FOUND", "message": "提交文件不存在。"})
    return connection, row, row


def _authorize_file(request: Request, row: sqlite3.Row) -> None:
    if request.headers.get("X-Student-Session"):
        student = _student_session(request, row["session_id"], require_active=False)
        if student["session_student_id"] != row["session_student_id"]:
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "无权访问该提交文件。"})
    else:
        _teacher_session(request, row["session_id"])
    # Round-bound files are only visible while their owning round is current.
    if row["round_id"]:
        connection = _connect(_db(request))
        try:
            _authorize_round_submission(connection, request, row)
        finally:
            connection.close()


def _preview_pdf_path(request: Request, row: sqlite3.Row) -> Path:
    source = Path(row["storage_path"])
    if not source.is_file():
        raise HTTPException(404, detail={"code": "FILE_STORAGE_MISSING", "message": "文件存储不存在。"})
    if row["file_type"] == "pdf":
        return source
    if row["file_type"] not in {"pptx", "docx"}:
        raise HTTPException(422, detail={"code": "PREVIEW_CONVERSION_FAILED", "message": "该文件类型没有 PDF 原格式预览。"})
    config = load_preview_settings()
    try:
        result = convert_to_pdf(
            source,
            get_submission_preview_dir(row["session_id"], row["submission_id"]),
            config,
            total_timeout_seconds=config.submission_timeout_seconds,
        )
        return result.pdf_path
    except PreviewConversionError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from None


@router.get("/api/submission-files/{file_id}/preview")
def preview_submission_file(file_id: str, request: Request) -> dict[str, object]:
    connection, row, _ = _file_and_submission(request, file_id)
    try:
        _authorize_file(request, row)
        path = Path(row["storage_path"])
        if not path.is_file():
            raise HTTPException(404, detail={"code": "FILE_STORAGE_MISSING", "message": "文件存储不存在。"})
        if row["file_type"] in {"pptx", "docx", "pdf"}:
            _preview_pdf_path(request, row)
            return {
                "status": "PREVIEW_OK",
                "file_id": row["id"], "filename": row["filename"], "file_type": row["file_type"],
                "preview_type": "pdf", "size_bytes": row["size_bytes"],
                "preview_url": f"/api/submission-files/{row['id']}/preview/pdf",
                "content_url": f"/api/submission-files/{row['id']}/content",
            }
        return {
            "status": "TEXT", "file_id": row["id"], "filename": row["filename"], "file_type": row["file_type"],
            "preview_type": row["preview_type"], "size_bytes": row["size_bytes"],
            "content_url": f"/api/submission-files/{row['id']}/content",
            "text": row["chunk_summary"],
        }
    finally:
        connection.close()


@router.get("/api/submission-files/{file_id}/content")
def submission_file_content(file_id: str, request: Request):
    connection, row, _ = _file_and_submission(request, file_id)
    try:
        _authorize_file(request, row)
        path = Path(row["storage_path"])
        if not path.is_file(): raise HTTPException(404, detail={"code": "FILE_STORAGE_MISSING", "message": "文件存储不存在。"})
        media = {"pdf": "application/pdf", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8"}[row["file_type"]]
        # Read into the response so the SQLite/temp storage file is not left
        # open by a deferred FileResponse on Windows.
        return Response(content=path.read_bytes(), media_type=media, headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'})
    finally:
        connection.close()


@router.get("/api/submission-files/{file_id}/preview/pdf")
def submission_preview_pdf(file_id: str, request: Request):
    connection, row, _ = _file_and_submission(request, file_id)
    try:
        _authorize_file(request, row)
        path = _preview_pdf_path(request, row)
        return Response(
            content=path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{Path(row["filename"]).stem}.pdf"'},
        )
    finally:
        connection.close()


class GenerateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(default="请基于材料生成一个适合课堂讨论的追问。", max_length=1000)


_submission_question_service: ReportQuestionService | None = None


def _get_submission_question_service() -> ReportQuestionService:
    """Use the same validated report-question LLM chain as stage 2B."""
    global _submission_question_service
    if _submission_question_service is None:
        _submission_question_service = ReportQuestionService(load_settings())
    return _submission_question_service


def _question_error(error: Exception) -> HTTPException:
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return HTTPException(502, detail={"code": "LLM_AUTHENTICATION_ERROR", "message": "大模型认证配置异常。"})
    if isinstance(error, RateLimitError):
        return HTTPException(429, detail={"code": "LLM_RATE_LIMITED", "message": "大模型请求过于频繁，请稍后重试。"})
    if isinstance(error, APITimeoutError):
        return HTTPException(504, detail={"code": "LLM_TIMEOUT", "message": "大模型请求超时，请稍后重试。"})
    if isinstance(error, APIConnectionError):
        return HTTPException(502, detail={"code": "LLM_UPSTREAM_UNAVAILABLE", "message": "大模型服务暂不可用，请稍后重试。"})
    if isinstance(error, APIStatusError):
        return HTTPException(502, detail={"code": "LLM_UPSTREAM_ERROR", "message": f"大模型服务返回异常状态（HTTP {error.status_code}）。"})
    if isinstance(error, ReportQuestionOutputError):
        return HTTPException(502, detail={"code": "LLM_OUTPUT_INVALID", "message": "大模型返回结果未通过材料来源校验，未保存提问记录。"})
    if isinstance(error, ValueError):
        return HTTPException(502, detail={"code": "LLM_OUTPUT_INVALID", "message": "大模型返回结果未通过结构或来源校验，未保存提问记录。"})
    return HTTPException(502, detail={"code": "LLM_UPSTREAM_UNAVAILABLE", "message": "大模型服务暂不可用，未保存提问记录。"})


def _question_payload(result: object, fallback_filename: str) -> dict[str, object]:
    data = getattr(result, "data", None)
    if not isinstance(data, dict):
        raise ValueError("提问结果结构无效")
    if data.get("status") == "insufficient":
        raise HTTPException(422, detail={"code": "MATERIAL_INSUFFICIENT", "message": str(data.get("notice") or "材料不足，无法生成有依据的提问。")})
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("提问结果缺少问题")
    item = questions[0]
    evidence = item.get("evidence") or []
    if isinstance(evidence, dict): evidence = [evidence]
    citations = []
    for entry in evidence:
        if not isinstance(entry, dict):
            raise ValueError("来源结构无效")
        citations.append({"filename": entry.get("filename") or fallback_filename, "location": entry.get("location", ""), "quote": entry.get("quote", "")})
    if not citations or not all(citation["location"] and citation["quote"] for citation in citations):
        raise ValueError("提问缺少真实材料位置")
    return {
        "question": item["question"],
        "basis_summary": item.get("basis_summary", ""),
        "relation_explanation": item.get("relation_explanation", ""),
        "citations": citations,
        "source_file": fallback_filename,
        "provider": "project_llm",
    }


@router.post("/api/submission-files/{file_id}/generate-question")
def generate_question(file_id: str, request: Request, payload: GenerateQuestionRequest | None = None) -> dict[str, object]:
    connection, row, _ = _file_and_submission(request, file_id)
    try:
        _teacher_session(request, row["session_id"], require_active=False)
        session = _session(request, row["session_id"])
        if session["status"] != "active":
            raise HTTPException(409, detail={"code": "CLASSROOM_ENDED", "message": "课堂已结束，不能发起提问。"})
        round_row = _authorize_round_submission(connection, request, row)
        prompt = (payload.prompt if payload else "请基于材料生成一个适合课堂讨论的追问。").strip()
        try:
            paths = [(row["filename"], Path(row["storage_path"]), row["id"])]
            if round_row is not None:
                sibling_rows = connection.execute(
                    """SELECT f.id,f.filename,f.storage_path FROM submission_files f JOIN submissions s ON s.id=f.submission_id
                       WHERE s.session_id=? AND s.session_student_id=? AND s.round_id=? AND s.status='submitted'
                       ORDER BY f.created_at,f.id""",
                    (row["session_id"], row["session_student_id"], row["round_id"]),
                ).fetchall()
                paths = [(item["filename"], Path(item["storage_path"]), item["id"]) for item in sibling_rows]
            parsed = [parse_material_file(path) for _, path, _ in paths]
            segments = tuple(segment for material in parsed for segment in material.segments)
            material = ParsedMaterial(
                material_name="；".join(name for name, _, _ in paths),
                material_type="MULTI",
                extracted_text="\n\n".join(item.extracted_text for item in parsed),
                segments=segments,
            )
            instruction = prompt if prompt != "请基于材料生成一个适合课堂讨论的追问。" else None
            result = _get_submission_question_service().generate(material, instruction=instruction)
            validated_data = getattr(result, "data", None)
            response = _question_payload(result, row["filename"])
        except HTTPException:
            raise
        except Exception as error:
            raise _question_error(error) from None
        question_id = str(uuid4()); created_at = _now()
        with connection:
            connection.execute("INSERT INTO teaching_questions(id,submission_file_id,teacher_account_id,prompt,response_json,created_at) VALUES (?,?,?,?,?,?)", (question_id, file_id, request.state.account["account_id"], prompt, json.dumps(validated_data, ensure_ascii=False), created_at))
        return {"question_id": question_id, "file_id": file_id, "prompt": prompt, "question": response["question"], "response": response, "response_json": response, "created_at": created_at}
    finally:
        connection.close()
