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


@router.get("/export.csv")
def export_history_csv(course_id: str, task_type: str | None = None, created_from: str | None = None, created_to: str | None = None, store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> StreamingResponse:
    _ensure_course(course_id, store)
    events, _ = history.list(course_id, task_type, created_from, created_to, 1, 100000)
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["id", "course_id", "created_at", "task_type", "student_id", "input_json", "output_json", "score", "level", "course_basis_json", "duration_ms"])
    for event in events:
        writer.writerow([event.id, event.course_id, event.created_at, event.task_type, event.student_id or "", json.dumps(event.input_json, ensure_ascii=False), json.dumps(event.output_json, ensure_ascii=False), event.score if event.score is not None else "", event.level or "", json.dumps(event.course_basis_json, ensure_ascii=False), event.duration_ms if event.duration_ms is not None else ""])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="teaching-history-{course_id}.csv"'})


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
