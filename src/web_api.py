from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import perf_counter
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from src.auth import require_business_access, router as auth_router
from src.classroom import router as classroom_router
from fastapi.staticfiles import StaticFiles
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pptx import Presentation

from src.config import ConfigError, Settings, load_settings
from src.course_data import CourseStore, get_course_store, router as course_router
from src.data_paths import course_directory
from src.course_materials import load_course_retriever, router as course_material_router
from src.teaching_history import get_history_store, router as history_router
from src.teaching_analytics import router as analytics_router
from src.learning_report import router as learning_report_router
from src.material_parser import (
    SUPPORTED_MATERIAL_TYPES,
    MaterialParseError,
    ParsedMaterial,
    parse_material_file,
    parse_text_material,
)
from src.rag_service import ModelOutputError, RAGService
from src.report_question_service import (
    ReportQuestionOutputError,
    ReportQuestionService,
    public_presentation_result,
    readable_material_text,
)
from src.source_mapper import (
    OriginalSourceRetriever,
    SourceMappingError,
    SourcePageMapper,
)
from src.submissions import router as submissions_router
from src.oral_input import router as oral_input_router
from src.collaboration import router as collaboration_router


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT_LENGTH = 1000
MAX_PRESENTATION_FILES = 10
MAX_PRESENTATION_FILE_BYTES = 50 * 1024 * 1024
MAX_PRESENTATION_TOTAL_FILE_BYTES = 100 * 1024 * 1024
MAX_PRESENTATION_TEXT_LENGTH = 30_000
MAX_PRESENTATION_SLIDES = 40
MATERIAL_TOO_LONG_MESSAGE = "材料文本超过30000字符，请删除附录、参考文献或无关内容后重试。"
OPTIMIZED_QUESTION_LEVELS = (
    ("easy", "简单", 60),
    ("medium", "中等", 80),
    ("hard", "困难", 100),
)


class QuestionOptimizeRequest(BaseModel):
    course_id: str
    question: str


class AnswerEvaluateRequest(BaseModel):
    course_id: str
    question: str
    student_answer: str


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseBasisItem(StrictResponseModel):
    source: str
    reason: str


class EvidenceItem(StrictResponseModel):
    source: str
    quote: str


class ScoreBreakdownItem(StrictResponseModel):
    key: str
    label: str
    max_score: int = Field(ge=1, le=100)
    anchor: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    evidence: list[EvidenceItem]


class QuestionEvaluation(StrictResponseModel):
    raw_score: int = Field(ge=0, le=100)
    floor_applied: bool
    score: int = Field(ge=60, le=100)
    level: Literal["简单", "思考型", "深度型"]
    evaluation: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    score_interpretation: str = Field(min_length=1)
    evidence_status: Literal["sufficient", "insufficient"]
    score_breakdown: list[ScoreBreakdownItem] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_level_matches_score(self) -> "QuestionEvaluation":
        expected = "简单" if self.score <= 75 else "思考型" if self.score <= 90 else "深度型"
        if self.level != expected:
            raise ValueError(f"level 必须与 score 对应为“{expected}”")
        if sum(item.score for item in self.score_breakdown) != self.raw_score:
            raise ValueError("raw_score 必须等于分项之和")
        if self.score != max(60, self.raw_score) or self.floor_applied != (self.raw_score < 60):
            raise ValueError("保底成绩或保底标记不正确")
        return self


class OptimizedQuestionItem(StrictResponseModel):
    question: str
    improvement_focus: str
    level: Literal["easy", "medium", "hard"]
    label: Literal["简单", "中等", "困难"]
    score: Literal[60, 80, 100]


class DeepQuestionItem(StrictResponseModel):
    question: str
    thinking_dimension: str


class QuestionOptimizeResponse(StrictResponseModel):
    task_type: Literal["question_optimize"]
    original_question: str
    question_evaluation: QuestionEvaluation
    optimized_questions: list[OptimizedQuestionItem] = Field(min_length=3, max_length=3)
    deep_questions: list[DeepQuestionItem] = Field(min_length=2, max_length=2)
    course_basis: list[CourseBasisItem] = Field(max_length=2)
    insufficiency_notice: str


class AnswerEvaluateResponse(StrictResponseModel):
    raw_score: int = Field(ge=0, le=100)
    floor_applied: bool
    task_type: Literal["answer_evaluate"]
    question: str
    student_answer: str
    score: int = Field(ge=60, le=100)
    level: Literal["简单", "思考型", "深度型"]
    score_interpretation: str = Field(min_length=1)
    evidence_status: Literal["sufficient", "insufficient"]
    score_breakdown: list[ScoreBreakdownItem] = Field(min_length=4, max_length=4)
    overall_evaluation: str
    strengths: list[str]
    issues: list[dict[str, str]]
    improvement_suggestions: list[str]
    improved_answer: str
    course_basis: list[CourseBasisItem] = Field(max_length=2)
    insufficiency_notice: str

    @model_validator(mode="after")
    def validate_level_and_total(self) -> "AnswerEvaluateResponse":
        expected = "简单" if self.score <= 75 else "思考型" if self.score <= 90 else "深度型"
        if self.level != expected:
            raise ValueError(f"level 必须与 score 对应为“{expected}”")
        if sum(item.score for item in self.score_breakdown) != self.raw_score:
            raise ValueError("raw_score 必须等于分项之和")
        if self.score != max(60, self.raw_score) or self.floor_applied != (self.raw_score < 60):
            raise ValueError("保底成绩或保底标记不正确")
        return self


class PresentationQuestionItem(StrictResponseModel):
    level: Literal["easy", "medium", "hard"]
    label: Literal["简单", "中等", "困难"]
    score: Literal[60, 80, 100]
    question: str = Field(min_length=1, max_length=60)
    source_hints: list[dict[str, str]] = Field(default_factory=list)
    basis_summary: str | None = None
    relation_explanation: str | None = None


class PresentationQuestionsResponse(StrictResponseModel):
    status: Literal["ready", "insufficient"] = "ready"
    notice: str = ""
    questions: list[PresentationQuestionItem] = Field(max_length=9)

    @model_validator(mode="after")
    def validate_three_questions_per_level(self) -> "PresentationQuestionsResponse":
        if self.status == "insufficient":
            if self.questions or not self.notice.strip():
                raise ValueError("材料不足时必须说明原因且无问题")
            return self
        expected = [
            (level, label, score)
            for level, label, score in OPTIMIZED_QUESTION_LEVELS
            for _ in range(3)
        ]
        actual = [(item.level, item.label, item.score) for item in self.questions]
        if actual != expected:
            raise ValueError("questions 必须依次包含简单、中等、困难各3题")
        return self


@dataclass(frozen=True)
class WebRuntime:
    service: RAGService
    source_mapper: SourcePageMapper
    settings: Settings


@dataclass(frozen=True)
class PresentationQuestionRuntime:
    service: ReportQuestionService


app = FastAPI(title="RAG教学辅助系统API", dependencies=[Depends(require_business_access)], docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(auth_router)
app.include_router(classroom_router)
app.include_router(course_router)
app.include_router(course_material_router)
app.include_router(history_router)
app.include_router(analytics_router)
app.include_router(learning_report_router)
app.include_router(submissions_router)
app.include_router(oral_input_router)
app.include_router(collaboration_router)

@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/auth/"):
        return JSONResponse(status_code=422, content={"detail": "请完整填写必填字段，并使用正确的文本格式。"})
    # Do not echo request inputs (which may contain sensitive information).
    return JSONResponse(status_code=422, content={"detail": "请求字段缺失或格式不正确。"})


_runtime: WebRuntime | None = None
_runtime_lock = Lock()
_course_runtime_cache: dict[str, tuple[WebRuntime, int]] = {}
_presentation_runtime: PresentationQuestionRuntime | None = None
_presentation_runtime_lock = Lock()


def _get_runtime() -> WebRuntime:
    global _runtime
    if _runtime is not None:
        return _runtime

    with _runtime_lock:
        if _runtime is None:
            settings = load_settings()
            service = RAGService(settings)
            source_mapper = SourcePageMapper.from_ppt_directory(PROJECT_ROOT / "ppt")
            service.retriever = OriginalSourceRetriever(service.retriever, source_mapper)
            _runtime = WebRuntime(service, source_mapper, settings)
    return _runtime


def _get_presentation_runtime() -> PresentationQuestionRuntime:
    global _presentation_runtime
    if _presentation_runtime is not None:
        return _presentation_runtime

    with _presentation_runtime_lock:
        if _presentation_runtime is None:
            settings = load_settings()
            _presentation_runtime = PresentationQuestionRuntime(
                service=ReportQuestionService(settings),
            )
    return _presentation_runtime


def _validate_input(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空。")
    if len(cleaned) > MAX_INPUT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}不能超过{MAX_INPUT_LENGTH}字。",
        )
    return cleaned


def _require_supported_course(course_id: str, store: CourseStore):
    course = store.get(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    if course_id != "default" and course.status != "ready":
        raise HTTPException(status_code=400, detail="该课程知识库尚未构建")
    return course


def _get_course_runtime(course_id: str, store: CourseStore) -> WebRuntime:
    if course_id == "default":
        return _get_runtime()
    base = course_directory(course_id) / "vector_db"
    index_mtime = (base / "course.index").stat().st_mtime_ns
    cached = _course_runtime_cache.get(course_id)
    if cached and cached[1] == index_mtime:
        return cached[0]
    settings = load_settings()
    retriever, mapper = load_course_retriever(course_id)
    service = RAGService(settings)
    service.retriever = retriever
    service.retriever = OriginalSourceRetriever(service.retriever, mapper)
    runtime = WebRuntime(service, mapper, settings)
    _course_runtime_cache[course_id] = (runtime, index_mtime)
    return runtime


def _save_teaching_event(course_store: CourseStore, course_id: str, task_type: str, input_data: dict, output_data: dict, started_at: float) -> None:
    get_history_store(course_store).add(
        course_id=course_id,
        task_type=task_type,
        input_data=input_data,
        output_data=output_data,
        duration_ms=round((perf_counter() - started_at) * 1000),
    )


def _add_optimized_question_levels(data: dict[str, object]) -> dict[str, object]:
    optimized_questions = data.get("optimized_questions")
    if not isinstance(optimized_questions, list) or len(optimized_questions) != 3:
        raise ValueError("optimized_questions 必须恰好包含3项。")

    enriched_questions: list[dict[str, object]] = []
    for item, (level, label, score) in zip(
        optimized_questions,
        OPTIMIZED_QUESTION_LEVELS,
    ):
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise ValueError("optimized_questions 每项必须包含字符串 question。")
        enriched_questions.append(
            {
                **item,
                "level": level,
                "label": label,
                "score": score,
            }
        )

    return {**data, "optimized_questions": enriched_questions}


def _safe_service_error(error: Exception) -> HTTPException:
    if isinstance(error, (AuthenticationError, PermissionDeniedError, APIStatusError)):
        message = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", str(error))
        message = re.sub(r"(?i)sk-[A-Za-z0-9_-]+", "[redacted]", message)
        print(
            "LLM upstream error: "
            f"type={type(error).__name__} "
            f"status={getattr(error, 'status_code', None)} "
            f"code={getattr(error, 'code', None)} "
            f"message={message[:500]}",
            file=sys.stderr,
        )
    if isinstance(error, APITimeoutError):
        return HTTPException(status_code=504, detail="大模型请求超时，请稍后重试。")
    if isinstance(error, RateLimitError):
        return HTTPException(status_code=429, detail="大模型请求过于频繁，请稍后重试。")
    if isinstance(error, APIConnectionError):
        return HTTPException(status_code=502, detail="暂时无法连接大模型服务，请稍后重试。")
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return HTTPException(status_code=502, detail="大模型服务认证或权限配置异常。")
    if isinstance(error, APIStatusError):
        return HTTPException(
            status_code=502,
            detail=f"大模型服务返回异常状态（HTTP {error.status_code}）。",
        )
    if isinstance(error, ModelOutputError):
        finish_reason = error.finish_reason or "未知"
        return HTTPException(
            status_code=502,
            detail=f"大模型返回结果未通过JSON校验（finish_reason={finish_reason}）。",
        )
    if isinstance(error, ReportQuestionOutputError):
        finish_reason = error.finish_reason or "未知"
        return HTTPException(
            status_code=502,
            detail=f"大模型返回的汇报问题未通过JSON校验（finish_reason={finish_reason}）。",
        )
    if isinstance(error, SourceMappingError):
        return HTTPException(status_code=500, detail="课程来源页码映射不可用。")
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=500, detail="知识库文件缺失，服务暂不可用。")
    if isinstance(error, ConfigError):
        return HTTPException(status_code=500, detail="服务配置不完整，请联系管理员。")
    if isinstance(error, ValueError):
        return HTTPException(status_code=502, detail="大模型返回结果未通过结构或来源校验。")
    return HTTPException(status_code=500, detail="服务处理请求时发生内部错误。")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/question-optimize", response_model=QuestionOptimizeResponse)
def question_optimize(
    request: QuestionOptimizeRequest,
    course_store: CourseStore = Depends(get_course_store),
) -> dict[str, object]:
    _require_supported_course(request.course_id, course_store)
    started_at = perf_counter()
    question = _validate_input(request.question, "问题")
    try:
        runtime = _get_course_runtime(request.course_id, course_store)
        result = runtime.service.question_optimize(
            question,
            runtime.settings.default_top_k,
        )
        enriched_data = _add_optimized_question_levels(result.data)
        payload = runtime.source_mapper.sanitize_value(enriched_data)
        payload = QuestionOptimizeResponse.model_validate(payload).model_dump()
        _save_teaching_event(course_store, request.course_id, "question_optimize", request.model_dump(), payload, started_at)
        return payload
    except HTTPException:
        raise
    except Exception as error:
        raise _safe_service_error(error) from None


@app.post("/api/answer-evaluate", response_model=AnswerEvaluateResponse)
def answer_evaluate(
    request: AnswerEvaluateRequest,
    course_store: CourseStore = Depends(get_course_store),
) -> dict[str, object]:
    _require_supported_course(request.course_id, course_store)
    started_at = perf_counter()
    question = _validate_input(request.question, "问题")
    student_answer = _validate_input(request.student_answer, "学生回答")
    try:
        runtime = _get_course_runtime(request.course_id, course_store)
        result = runtime.service.answer_evaluate(
            question,
            student_answer,
            runtime.settings.default_top_k,
        )
        payload = runtime.source_mapper.sanitize_value(result.data)
        payload = AnswerEvaluateResponse.model_validate(payload).model_dump()
        _save_teaching_event(course_store, request.course_id, "answer_evaluate", request.model_dump(), payload, started_at)
        return payload
    except HTTPException:
        raise
    except Exception as error:
        raise _safe_service_error(error) from None


def _combine_presentation_materials(materials: list[ParsedMaterial]) -> ParsedMaterial:
    valid_materials = [material for material in materials if material.extracted_text.strip()]
    if not valid_materials:
        raise HTTPException(status_code=400, detail="材料内容不能为空。")
    if len(valid_materials) == 1:
        if len(valid_materials[0].extracted_text) > MAX_PRESENTATION_TEXT_LENGTH:
            raise HTTPException(status_code=400, detail=MATERIAL_TOO_LONG_MESSAGE)
        return valid_materials[0]

    sections = [
        f"===== {material.material_name}（{material.material_type}） =====\n{material.extracted_text}"
        for material in valid_materials
    ]
    combined_text = "\n\n".join(sections)
    if len(combined_text) > MAX_PRESENTATION_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=MATERIAL_TOO_LONG_MESSAGE)
    return ParsedMaterial(
        material_name="上传文件与补充文本",
        material_type="组合材料",
        extracted_text=combined_text,
        segments=tuple(seg for material in valid_materials for seg in material.segments),
    )


async def _parse_uploaded_material(upload: UploadFile) -> tuple[ParsedMaterial, int]:
    original_name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_MATERIAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail="不支持该材料格式，请上传PPTX、DOCX、Markdown或TXT文件。",
        )

    try:
        content = await upload.read(MAX_PRESENTATION_FILE_BYTES + 1)
    finally:
        await upload.close()
    if len(content) > MAX_PRESENTATION_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件“{original_name}”超过单文件50MB限制。",
        )
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空。")

    if suffix == ".pptx":
        try:
            slide_count = len(Presentation(BytesIO(content)).slides)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="PPTX材料解析失败，请确认文件未损坏且格式正确。",
            ) from None
        if slide_count > MAX_PRESENTATION_SLIDES:
            raise HTTPException(
                status_code=400,
                detail="PPT超过40页，请上传核心汇报页或删除附录后重试。",
            )

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        parsed = parse_material_file(temporary_path)
    except MaterialParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return (
        ParsedMaterial(
            material_name=original_name,
            material_type=parsed.material_type,
            extracted_text=parsed.extracted_text,
            segments=tuple(replace(seg, filename=original_name) for seg in parsed.segments),
        ),
        len(content),
    )


@app.post("/api/presentation-preview")
@app.post(
    "/api/presentation-questions",
    response_model=PresentationQuestionsResponse,
    summary="根据汇报材料生成分级问题",
    description="使用multipart/form-data提交材料；files最多10个，可与text单独或同时提供。",
)
async def presentation_questions(
    request: Request,
    course_id: Annotated[str, Form(description="本次汇报所属课程")],
    files: Annotated[
        list[UploadFile] | None,
        File(description="可选；最多10个PPTX、DOCX、Markdown或TXT文件；单文件50MB、合计100MB；PPTX单个最多40页"),
    ] = None,
    text: Annotated[
        str | None,
        Form(description="可选；粘贴纯文本；可与files同时提交，合并后最多30000字符"),
    ] = None,
    course_store: CourseStore = Depends(get_course_store),
) -> dict[str, object]:
    if course_store.get(course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    started_at = perf_counter()
    uploads = files or []
    if not uploads and (text is None or not text.strip()):
        raise HTTPException(
            status_code=400,
            detail="请至少上传一个文件或输入纯文本材料。",
        )
    if len(uploads) > MAX_PRESENTATION_FILES:
        raise HTTPException(status_code=400, detail="一次最多上传10个文件。")

    known_sizes = [upload.size for upload in uploads]
    for upload, size in zip(uploads, known_sizes):
        if size is not None and size > MAX_PRESENTATION_FILE_BYTES:
            original_name = (upload.filename or "未命名文件").replace("\\", "/").rsplit("/", 1)[-1]
            raise HTTPException(
                status_code=400,
                detail=f"文件“{original_name}”超过单文件50MB限制。",
            )
    if all(size is not None for size in known_sizes) and sum(known_sizes) > MAX_PRESENTATION_TOTAL_FILE_BYTES:
        raise HTTPException(status_code=400, detail="本次所有文件合计不能超过100MB。")

    materials: list[ParsedMaterial] = []
    total_file_bytes = 0
    for upload in uploads:
        material, file_bytes = await _parse_uploaded_material(upload)
        total_file_bytes += file_bytes
        if total_file_bytes > MAX_PRESENTATION_TOTAL_FILE_BYTES:
            raise HTTPException(status_code=400, detail="本次所有文件合计不能超过100MB。")
        materials.append(material)
    if text is not None and text.strip():
        materials.append(parse_text_material(text.strip(), "补充纯文本材料"))
    material = _combine_presentation_materials(materials)
    if request.url.path == "/api/presentation-preview":
        return {"materials": [
            {"filename": item.material_name, "overview": readable_material_text("\n".join(seg.text for seg in item.segments))[:2000]}
            for item in materials
        ]}

    try:
        result = _get_presentation_runtime().service.generate(material)
        payload = result.data
        _save_teaching_event(course_store, course_id, "presentation_questions", {"course_id": course_id, "file_count": len(uploads), "text_length": len(text or "")}, payload, started_at)
        return public_presentation_result(payload)
    except HTTPException:
        raise
    except ReportQuestionOutputError:
        raise HTTPException(status_code=502, detail="汇报问题生成结果未通过校验，请重试；这不代表材料不足。") from None
    except Exception as error:
        raise _safe_service_error(error) from None


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="frontend-assets",
)


@app.get("/{path:path}", include_in_schema=False)
async def serve_frontend(path: str) -> FileResponse:
    """Serve the freshly built web client while preserving the API namespace."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    index_path = FRONTEND_DIST / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=503, detail="Web client is not built")
    return FileResponse(index_path)
