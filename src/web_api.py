from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
from src.course_data import router as course_router
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
)
from src.source_mapper import (
    OriginalSourceRetriever,
    SourceMappingError,
    SourcePageMapper,
)


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
    question: str


class AnswerEvaluateRequest(BaseModel):
    question: str
    student_answer: str


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseBasisItem(StrictResponseModel):
    source: str
    reason: str


class QuestionEvaluation(StrictResponseModel):
    score: int = Field(ge=60, le=100)
    level: Literal["简单", "思考型", "深度型"]
    evaluation: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_level_matches_score(self) -> "QuestionEvaluation":
        expected = "简单" if self.score <= 75 else "思考型" if self.score <= 90 else "深度型"
        if self.level != expected:
            raise ValueError(f"level 必须与 score 对应为“{expected}”")
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


class PresentationQuestionItem(StrictResponseModel):
    level: Literal["easy", "medium", "hard"]
    label: Literal["简单", "中等", "困难"]
    score: Literal[60, 80, 100]
    question: str = Field(min_length=1, max_length=60)


class PresentationQuestionsResponse(StrictResponseModel):
    questions: list[PresentationQuestionItem] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def validate_three_questions_per_level(self) -> "PresentationQuestionsResponse":
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


app = FastAPI(title="RAG教学辅助系统API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(course_router)

_runtime: WebRuntime | None = None
_runtime_lock = Lock()
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
def question_optimize(request: QuestionOptimizeRequest) -> dict[str, object]:
    question = _validate_input(request.question, "问题")
    try:
        runtime = _get_runtime()
        result = runtime.service.question_optimize(
            question,
            runtime.settings.default_top_k,
        )
        enriched_data = _add_optimized_question_levels(result.data)
        return runtime.source_mapper.sanitize_value(enriched_data)
    except HTTPException:
        raise
    except Exception as error:
        raise _safe_service_error(error) from None


@app.post("/api/answer-evaluate")
def answer_evaluate(request: AnswerEvaluateRequest) -> dict[str, object]:
    question = _validate_input(request.question, "问题")
    student_answer = _validate_input(request.student_answer, "学生回答")
    try:
        runtime = _get_runtime()
        result = runtime.service.answer_evaluate(
            question,
            student_answer,
            runtime.settings.default_top_k,
        )
        return runtime.source_mapper.sanitize_value(result.data)
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
        ),
        len(content),
    )


@app.post(
    "/api/presentation-questions",
    response_model=PresentationQuestionsResponse,
    summary="根据汇报材料生成分级问题",
    description="使用multipart/form-data提交材料；files最多10个，可与text单独或同时提供。",
)
async def presentation_questions(
    files: Annotated[
        list[UploadFile] | None,
        File(description="可选；最多10个PPTX、DOCX、Markdown或TXT文件；单文件50MB、合计100MB；PPTX单个最多40页"),
    ] = None,
    text: Annotated[
        str | None,
        Form(description="可选；粘贴纯文本；可与files同时提交，合并后最多30000字符"),
    ] = None,
) -> dict[str, object]:
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

    try:
        result = _get_presentation_runtime().service.generate(material)
        return result.data
    except HTTPException:
        raise
    except Exception as error:
        raise _safe_service_error(error) from None
