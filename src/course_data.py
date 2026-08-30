from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COURSE_DB_PATH = PROJECT_ROOT / "storage" / "courses.db"
COURSE_STATUSES = ("draft", "building", "ready", "failed")


def _clean_text(value: str) -> str:
    return value.strip()


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("name 不能为空")
    return cleaned


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    grade_level: str = Field(default="", max_length=100)
    teaching_goal: str = Field(default="", max_length=2000)

    _strip_name = field_validator("name", mode="before")(_clean_name)
    _strip_text = field_validator("description", "grade_level", "teaching_goal", mode="before")(_clean_text)


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    grade_level: str | None = Field(default=None, max_length=100)
    teaching_goal: str | None = Field(default=None, max_length=2000)
    status: str | None = None

    _strip_name = field_validator("name", mode="before")(_clean_name)
    _strip_text = field_validator("description", "grade_level", "teaching_goal", mode="before")(_clean_text)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in COURSE_STATUSES:
            raise ValueError("status 必须是 draft、building、ready 或 failed")
        return value


class Course(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    grade_level: str
    teaching_goal: str
    created_at: str
    status: Literal["draft", "building", "ready", "failed"]


class CourseStore:
    """SQLite persistence for courses; association checks are extension hooks."""

    def __init__(self, db_path: Path | str = COURSE_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.ensure_default_course()

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
                """CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    grade_level TEXT NOT NULL DEFAULT '',
                    teaching_goal TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'building', 'ready', 'failed'))
                )"""
            )

    def ensure_default_course(self) -> Course:
        """Create the built-in course once; its knowledge sources remain global and read-only."""
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO courses
                   (id, name, description, grade_level, teaching_goal, created_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "default",
                    "默认课程",
                    "关联现有全局课程资料",
                    "",
                    "",
                    datetime.now(timezone.utc).isoformat(),
                    "ready",
                ),
            )
        return self.get("default")  # type: ignore[return-value]

    @staticmethod
    def _course(row: sqlite3.Row) -> Course:
        return Course(**dict(row))

    def create(self, data: CourseCreate) -> Course:
        course = Course(
            id=str(uuid4()),
            name=data.name,
            description=data.description,
            grade_level=data.grade_level,
            teaching_goal=data.teaching_goal,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="draft",
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO courses VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(course.model_dump().values()),
            )
        return course

    def list(self) -> list[Course]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM courses ORDER BY created_at, id").fetchall()
        return [self._course(row) for row in rows]

    def get(self, course_id: str) -> Course | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        return self._course(row) if row else None

    def update(self, course_id: str, data: CourseUpdate) -> Course | None:
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return self.get(course_id)
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = [*changes.values(), course_id]
        with self._connect() as connection:
            cursor = connection.execute(f"UPDATE courses SET {assignments} WHERE id = ?", values)
            if cursor.rowcount == 0:
                return None
        return self.get(course_id)

    def has_materials(self, course_id: str) -> bool:
        return False

    def has_history(self, course_id: str) -> bool:
        return False

    def delete(self, course_id: str) -> bool:
        if self.has_materials(course_id) or self.has_history(course_id):
            raise ValueError("课程存在关联资料或历史记录，不能删除")
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        return cursor.rowcount > 0

    def set_status(self, course_id: str, status_value: str) -> Course | None:
        if status_value not in COURSE_STATUSES:
            raise ValueError("无效课程状态")
        with self._connect() as connection:
            cursor = connection.execute("UPDATE courses SET status = ? WHERE id = ?", (status_value, course_id))
            if cursor.rowcount == 0:
                return None
        return self.get(course_id)


_store: CourseStore | None = None


def get_course_store() -> CourseStore:
    global _store
    if _store is None:
        _store = CourseStore()
    return _store


def _find_or_404(course_id: str, store: CourseStore) -> Course:
    course = store.get(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", response_model=Course, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, store: CourseStore = Depends(get_course_store)) -> Course:
    return store.create(payload)


@router.get("", response_model=list[Course])
def list_courses(store: CourseStore = Depends(get_course_store)) -> list[Course]:
    return store.list()


@router.get("/{course_id}", response_model=Course)
def get_course(course_id: str, store: CourseStore = Depends(get_course_store)) -> Course:
    return _find_or_404(course_id, store)


@router.patch("/{course_id}", response_model=Course)
@router.put("/{course_id}", response_model=Course)
def update_course(course_id: str, payload: CourseUpdate, store: CourseStore = Depends(get_course_store)) -> Course:
    _find_or_404(course_id, store)
    return store.update(course_id, payload)  # type: ignore[return-value]


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: str, store: CourseStore = Depends(get_course_store)) -> None:
    _find_or_404(course_id, store)
    try:
        store.delete(course_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
