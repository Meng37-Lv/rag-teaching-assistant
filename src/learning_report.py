from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.config import load_settings
from src.course_data import CourseStore, get_course_store
from src.llm_client import LLMClient
from src.teaching_analytics import calculate_statistics
from src.teaching_history import TeachingHistoryStore, get_history_store


SECTION_NAMES = ("整体概况", "高频疑点", "常见误区", "薄弱知识点", "思维能力", "代表证据", "教学建议")


class ReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conclusion: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class LearningReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    整体概况: list[ReportItem]
    高频疑点: list[ReportItem]
    常见误区: list[ReportItem]
    薄弱知识点: list[ReportItem]
    思维能力: list[ReportItem]
    代表证据: list[ReportItem]
    教学建议: list[ReportItem]


class LearningReportRequest(BaseModel):
    created_from: str | None = None
    created_to: str | None = None


def _representative_cases(events) -> list[dict]:
    cases = []
    for event in events[:5]:
        input_data = event.input_json if isinstance(event.input_json, dict) else {}
        output_data = event.output_json if isinstance(event.output_json, dict) else {}
        cases.append({
            "event_id": event.id,
            "task_type": event.task_type,
            "input_summary": str(input_data.get("question") or "无文本问题")[:200],
            "score": event.score,
            "level": event.level,
            "issues": output_data.get("issues", [])[:3] if isinstance(output_data.get("issues"), list) else [],
            "course_basis": event.course_basis_json[:3],
        })
    return cases


def generate_report_payload(events, llm) -> LearningReportContent:
    statistics = calculate_statistics(events)
    safe_payload = {"统计": statistics, "去标识化代表案例": _representative_cases(events)}
    system = "你是教学数据分析助手。只能依据给定统计和案例生成报告，不得补充外部事实。每项结论必须在evidence中引用具体计数、比例、event_id或课程依据。只输出合法JSON。"
    schema = {name: [{"conclusion": "结论", "evidence": "对应统计或案例证据"}] for name in SECTION_NAMES}
    response = llm.complete([{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"数据": safe_payload, "输出结构": schema}, ensure_ascii=False)}], max_tokens=2200)
    try:
        return LearningReportContent.model_validate(json.loads(response.content))
    except Exception as error:
        raise HTTPException(status_code=502, detail="AI学情报告未通过结构校验") from error


router = APIRouter(prefix="/api/courses/{course_id}/learning-report", tags=["learning-report"])


@router.post("")
def create_learning_report(course_id: str, request: LearningReportRequest, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> dict:
    if store.get(course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    events, _ = history.list(course_id, created_from=request.created_from, created_to=request.created_to, page=1, page_size=100000)
    if len(events) < 10:
        raise HTTPException(status_code=400, detail="数据不足：至少需要10条教学记录才能生成AI学情报告")
    report = generate_report_payload(events, LLMClient(load_settings()))
    return {"course_id": course_id, "created_from": request.created_from, "created_to": request.created_to, "record_count": len(events), "generated_at": datetime.now(timezone.utc).isoformat(), "report": report.model_dump()}
