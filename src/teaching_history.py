from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.course_data import CourseStore, get_course_store


class TeachingEvent(BaseModel):
    id: str
    course_id: str
    created_at: str
    task_type: str
    student_id: str | None
    input_json: dict
    output_json: dict
    score: int | None
    level: str | None
    course_basis_json: list
    duration_ms: int | None


class TeachingHistoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS teaching_events (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    student_id TEXT,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    score INTEGER,
                    level TEXT,
                    course_basis_json TEXT NOT NULL,
                    duration_ms INTEGER
                )"""
            )

    @staticmethod
    def _event(row: sqlite3.Row) -> TeachingEvent:
        data = dict(row)
        data["input_json"] = json.loads(data["input_json"])
        data["output_json"] = json.loads(data["output_json"])
        data["course_basis_json"] = json.loads(data["course_basis_json"])
        return TeachingEvent(**data)

    def add(self, *, course_id: str, task_type: str, input_data: dict, output_data: dict, duration_ms: int | None = None, student_id: str | None = None) -> TeachingEvent:
        evaluation = output_data.get("question_evaluation") if isinstance(output_data, dict) else None
        direct_score = output_data.get("score") if isinstance(output_data, dict) else None
        direct_level = output_data.get("level") if isinstance(output_data, dict) else None
        event = TeachingEvent(
            id=str(uuid4()), course_id=course_id, created_at=datetime.now(timezone.utc).isoformat(),
            task_type=task_type, student_id=student_id, input_json=input_data, output_json=output_data,
            score=evaluation.get("score") if isinstance(evaluation, dict) else direct_score,
            level=evaluation.get("level") if isinstance(evaluation, dict) else direct_level,
            course_basis_json=output_data.get("course_basis", []) if isinstance(output_data, dict) else [],
            duration_ms=duration_ms,
        )
        with self._connect() as connection:
            connection.execute("INSERT INTO teaching_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event.id, event.course_id, event.created_at, event.task_type, event.student_id, json.dumps(event.input_json, ensure_ascii=False), json.dumps(event.output_json, ensure_ascii=False), event.score, event.level, json.dumps(event.course_basis_json, ensure_ascii=False), event.duration_ms))
        return event

    def list(self, course_id: str, task_type: str | None = None, created_from: str | None = None, created_to: str | None = None, page: int = 1, page_size: int = 20) -> tuple[list[TeachingEvent], int]:
        clauses = ["course_id = ?"]
        params: list[object] = [course_id]
        if task_type:
            clauses.append("task_type = ?"); params.append(task_type)
        if created_from:
            clauses.append("created_at >= ?"); params.append(created_from)
        if created_to:
            clauses.append("created_at <= ?"); params.append(created_to)
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with self._connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM teaching_events WHERE {where}", params).fetchone()[0]
            rows = connection.execute(f"SELECT * FROM teaching_events WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", [*params, page_size, offset]).fetchall()
        return [self._event(row) for row in rows], int(total)

    def get(self, course_id: str, event_id: str) -> TeachingEvent | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM teaching_events WHERE course_id = ? AND id = ?", (course_id, event_id)).fetchone()
        return self._event(row) if row else None

    def delete(self, course_id: str, event_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM teaching_events WHERE course_id = ? AND id = ?", (course_id, event_id))
        return cursor.rowcount > 0

    def clear(self, course_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM teaching_events WHERE course_id = ?", (course_id,))
        return cursor.rowcount


_history_store: TeachingHistoryStore | None = None


def get_history_store(store: CourseStore = Depends(get_course_store)) -> TeachingHistoryStore:
    global _history_store
    if _history_store is None or _history_store.db_path != store.db_path:
        _history_store = TeachingHistoryStore(store.db_path)
    return _history_store


def _ensure_course(course_id: str, store: CourseStore) -> None:
    if store.get(course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")


router = APIRouter(prefix="/api/courses/{course_id}/history", tags=["teaching-history"])

TASK_NAMES = {
    "question_optimize": "问题优化",
    "answer_evaluate": "答案评价",
    "presentation_questions": "汇报提问",
}


def _first_text(value: object, keys: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _input_summary(event: TeachingEvent) -> str:
    text = _first_text(event.input_json, ("question", "student_answer", "text", "content"))
    if text:
        return text[:500]
    count = event.input_json.get("file_count") if isinstance(event.input_json, dict) else None
    length = event.input_json.get("text_length") if isinstance(event.input_json, dict) else None
    if count or length:
        return f"汇报材料（{count or 0}个文件，{length or 0}字）"
    return "教学操作"


def _result_summary(event: TeachingEvent) -> str:
    output = event.output_json if isinstance(event.output_json, dict) else {}
    text = _first_text(output, ("optimized_question", "evaluation", "feedback", "answer", "summary"))
    if text:
        return text[:500]
    questions = output.get("questions")
    if isinstance(questions, list):
        readable = [str(item.get("question") if isinstance(item, dict) else item).strip() for item in questions[:3]]
        return "；".join(item for item in readable if item)[:500]
    issues = output.get("issues")
    if isinstance(issues, list):
        readable = [str(item.get("description") or item.get("type") if isinstance(item, dict) else item).strip() for item in issues[:3]]
        return "；".join(item for item in readable if item)[:500]
    return "已生成教学反馈"


def _basis_summary(event: TeachingEvent) -> str:
    values = []
    for item in event.course_basis_json[:5]:
        if isinstance(item, dict):
            source = str(item.get("source") or "").strip()
            reason = str(item.get("reason") or "").strip()
            values.append("：".join(part for part in (source, reason) if part))
        else:
            values.append(str(item).strip())
    return "；".join(value for value in values if value)


@router.get("/export.csv")
def export_history_csv(course_id: str, task_type: str | None = None, created_from: str | None = None, created_to: str | None = None, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> StreamingResponse:
    _ensure_course(course_id, store)
    events, total = history.list(course_id, task_type, created_from, created_to, 1, 100000)
    if total == 0:
        raise HTTPException(status_code=404, detail="暂无可导出历史")
    output = io.StringIO(); output.write("\ufeff"); writer = csv.writer(output)
    writer.writerow(["时间", "功能", "问题/输入", "结果摘要", "score", "level", "课程依据"])
    for event in events:
        writer.writerow([event.created_at, TASK_NAMES.get(event.task_type, event.task_type), _input_summary(event), _result_summary(event), event.score if event.score is not None else "", event.level or "", _basis_summary(event)])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="teaching-history-{course_id}.csv"'})


@router.get("")
def list_history(course_id: str, task_type: str | None = None, created_from: str | None = None, created_to: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> dict:
    _ensure_course(course_id, store)
    events, total = history.list(course_id, task_type, created_from, created_to, page, page_size)
    return {"items": [event.model_dump() for event in events], "total": total, "page": page, "page_size": page_size}


@router.get("/{event_id}", response_model=TeachingEvent)
def get_history_event(course_id: str, event_id: str, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> TeachingEvent:
    _ensure_course(course_id, store)
    event = history.get(course_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return event


@router.delete("/{event_id}", status_code=204)
def delete_history_event(course_id: str, event_id: str, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> None:
    _ensure_course(course_id, store)
    if not history.delete(course_id, event_id):
        raise HTTPException(status_code=404, detail="历史记录不存在")


@router.delete("", status_code=200)
def clear_history(course_id: str, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> dict[str, int]:
    _ensure_course(course_id, store)
    return {"deleted": history.clear(course_id)}
