from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.auth import get_accounts
from src.report_question_service import ReportQuestionOutputError


MAX_ORAL_TEXT = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


def _con(request: Request) -> sqlite3.Connection:
    c = sqlite3.connect(get_accounts(request).db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _student(request: Request, session_id: str, active: bool = True) -> sqlite3.Row:
    token = request.headers.get("X-Student-Session", "")
    c = _con(request)
    row = c.execute("""SELECT cs.*,s.status AS session_status, s.class_id,c.course_id
        FROM classroom_students cs JOIN classroom_sessions s ON s.session_id=cs.session_id
        JOIN classes c ON c.class_id=s.class_id
        WHERE cs.session_id=? AND cs.student_token_hash=?""", (session_id, _hash(token))).fetchone()
    c.close()
    if row is None or row["status"] != "confirmed":
        raise HTTPException(403, "学生会话无效或尚未确认。")
    if active and row["session_status"] != "active":
        raise HTTPException(409, "课堂已结束，不能输入或同步。")
    return row


def _teacher(request: Request, session_id: str, active: bool = False) -> sqlite3.Row:
    c = _con(request)
    row = c.execute("SELECT s.session_id,s.status,c.course_id FROM classroom_sessions s JOIN classes c ON c.class_id=s.class_id WHERE s.session_id=?", (session_id,)).fetchone()
    c.close()
    if row is None:
        raise HTTPException(404, "课堂不存在。")
    if not get_accounts(request).owns(request.state.account["account_id"], row["course_id"]):
        raise HTTPException(404, "课程不存在或无权访问。")
    if active and row["status"] != "active":
        raise HTTPException(409, "课堂已结束。")
    return row


def _plain(text: str, label: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise HTTPException(400, f"{label}不能为空。")
    if len(value) > MAX_ORAL_TEXT:
        raise HTTPException(400, f"{label}不能超过{MAX_ORAL_TEXT}字。")
    return value


class DraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(question|answer)$")
    body: str = Field(default="", max_length=MAX_ORAL_TEXT)


class OralTextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=MAX_ORAL_TEXT)


def _tokenize(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9_-]*|\d+(?:\.\d+)?%?", text)}


def validate_cleanup(original: str, cleaned: str) -> bool:
    if not cleaned.strip() or len(cleaned) > len(original) + 20:
        return False
    return _tokenize(cleaned) <= _tokenize(original)


def simple_cleanup(text: str) -> str:
    value = re.sub(r"(呃|嗯|那个|就是|然后|啊|呢|吧)[，、。！？\s]*", "", text.strip())
    value = re.sub(r"([，、。！？])\1+", r"\1", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip(" ，、") or text.strip()


def polish_question(text: str) -> tuple[str, str]:
    """Replaceable LLM boundary; deterministic cleanup is safe for local use/tests."""
    cleaned = simple_cleanup(text)
    return (cleaned, "ready" if validate_cleanup(text, cleaned) else "unformatted")


def _student_name(row: sqlite3.Row) -> str:
    return row["name"] or row["requested_name"] or "学生"


def _question(row: sqlite3.Row) -> dict:
    return {"question_id": row["id"], "student_id": row["student_id"], "student_name": _student_name(row), "original_text": row["original_text"], "cleaned_text": row["cleaned_text"], "cleanup_status": row["cleanup_status"], "created_at": row["created_at"]}


def _answer(row: sqlite3.Row) -> dict:
    return {"answer_id": row["id"], "student_id": row["student_id"], "student_name": _student_name(row), "question_id": row["question_id"], "original_text": row["original_text"], "cleaned_text": row["cleaned_text"], "cleanup_status": row["cleanup_status"], "created_at": row["created_at"]}


router = APIRouter(tags=["oral-input"])


@router.patch("/api/sessions/{session_id}/oral-drafts")
def save_draft(session_id: str, payload: DraftPayload, request: Request):
    student = _student(request, session_id, active=True)
    body = payload.body.strip()
    c = _con(request)
    with c:
        if body:
            c.execute("""INSERT INTO oral_drafts(id,session_id,session_student_id,kind,body,updated_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(session_student_id,kind) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at""", (str(uuid4()), session_id, student["session_student_id"], payload.kind, body, _now()))
        else:
            c.execute("DELETE FROM oral_drafts WHERE session_student_id=? AND kind=?", (student["session_student_id"], payload.kind))
    c.close()
    return {"kind": payload.kind, "body": body, "updated_at": _now()}


@router.get("/api/sessions/{session_id}/oral-drafts")
def list_drafts(session_id: str, request: Request):
    _teacher(request, session_id, active=False)
    c = _con(request); rows = c.execute("""SELECT d.*,cs.student_id,cs.requested_name,st.name
        FROM oral_drafts d JOIN classroom_students cs ON cs.session_student_id=d.session_student_id
        LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE d.session_id=? ORDER BY d.updated_at""", (session_id,)).fetchall(); c.close()
    return [{"student_id": row["student_id"], "student_name": _student_name(row), "kind": row["kind"], "body": row["body"], "updated_at": row["updated_at"]} for row in rows]


@router.get("/api/sessions/{session_id}/oral-state")
def oral_state(session_id: str, request: Request):
    student_token = request.headers.get("X-Student-Session", "")
    c = _con(request)
    if student_token:
        student = _student(request, session_id, active=False)
        rows = c.execute("SELECT * FROM oral_drafts WHERE session_student_id=?", (student["session_student_id"],)).fetchall()
        q = c.execute("""SELECT q.*,cs.student_id,cs.requested_name,st.name FROM oral_questions q
            JOIN classroom_students cs ON cs.session_student_id=q.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id
            WHERE q.session_id=? ORDER BY q.created_at DESC LIMIT 1""", (session_id,)).fetchone()
        answers = c.execute("SELECT a.*,cs.student_id,cs.requested_name,st.name FROM oral_answers a JOIN classroom_students cs ON cs.session_student_id=a.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE a.question_id=? AND a.session_student_id=? ORDER BY a.created_at", (q["id"], student["session_student_id"])) .fetchall() if q else []
        c.close()
        current = _question(q) if q else None
        if current: current.pop("student_id", None)
        visible_answers = []
        for answer in answers:
            item = _answer(answer); item.pop("student_id", None); visible_answers.append(item)
        return {"drafts": [{"kind": r["kind"], "body": r["body"], "updated_at": r["updated_at"]} for r in rows], "current_question": current, "answers": visible_answers}
    _teacher(request, session_id, active=False)
    q = c.execute("""SELECT q.*,cs.student_id,cs.requested_name,st.name FROM oral_questions q
        JOIN classroom_students cs ON cs.session_student_id=q.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id
        WHERE q.session_id=? ORDER BY q.created_at DESC LIMIT 1""", (session_id,)).fetchone()
    drafts = c.execute("""SELECT d.*,cs.student_id,cs.requested_name,st.name FROM oral_drafts d JOIN classroom_students cs ON cs.session_student_id=d.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE d.session_id=? ORDER BY d.updated_at""", (session_id,)).fetchall()
    answers = c.execute("""SELECT a.*,cs.student_id,cs.requested_name,st.name FROM oral_answers a JOIN classroom_students cs ON cs.session_student_id=a.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id WHERE a.question_id=? ORDER BY a.created_at""", (q["id"],)).fetchall() if q else []
    c.close()
    return {"drafts": [{"student_id": r["student_id"], "student_name": _student_name(r), "kind": r["kind"], "body": r["body"], "updated_at": r["updated_at"]} for r in drafts], "current_question": _question(q) if q else None, "answers": [_answer(r) for r in answers]}


@router.post("/api/sessions/{session_id}/oral-questions")
def submit_question(session_id: str, payload: OralTextPayload, request: Request):
    student = _student(request, session_id, active=True); original = _plain(payload.body, "问题")
    try: cleaned, status = polish_question(original)
    except Exception: cleaned, status = original, "unformatted"
    if status != "ready" or not validate_cleanup(original, cleaned):
        cleaned, status = original, "unformatted"
    question_id = str(uuid4()); created = _now(); c = _con(request)
    with c:
        c.execute("INSERT INTO oral_questions VALUES(?,?,?,?,?,?,?)", (question_id, session_id, student["session_student_id"], original, cleaned if status == "ready" else original, status, created))
        c.execute("DELETE FROM oral_drafts WHERE session_student_id=? AND kind='question'", (student["session_student_id"],))
    c.close()
    return {"question_id": question_id, "original_text": original, "cleaned_text": cleaned if status == "ready" else original, "cleanup_status": status, "created_at": created}


@router.post("/api/sessions/{session_id}/oral-answers")
def submit_answer(session_id: str, payload: OralTextPayload, request: Request):
    student = _student(request, session_id, active=True); original = _plain(payload.body, "回答"); c = _con(request)
    q = c.execute("""SELECT q.*,cs.student_id,cs.requested_name,st.name FROM oral_questions q
        JOIN classroom_students cs ON cs.session_student_id=q.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id
        WHERE q.session_id=? ORDER BY q.created_at DESC LIMIT 1""", (session_id,)).fetchone()
    if q is None:
        c.close(); raise HTTPException(409, "当前没有待回答问题，请等待学生提交问题。")
    answer_id = str(uuid4()); created = _now()
    with c:
        c.execute("INSERT INTO oral_answers VALUES(?,?,?,?,?,?,?,?)", (answer_id, session_id, student["session_student_id"], q["id"], original, "", "pending", created))
        c.execute("DELETE FROM oral_drafts WHERE session_student_id=? AND kind='answer'", (student["session_student_id"],))
    c.close()
    return {"answer_id": answer_id, "question_id": q["id"], "question": _question(q), "original_text": original, "cleaned_text": "", "cleanup_status": "pending", "created_at": created}


def _teacher_action(request: Request, answer_id: str | None = None, question_id: str | None = None):
    c = _con(request)
    if answer_id:
        row = c.execute("""SELECT a.*,q.original_text AS question_original,q.cleaned_text AS question_cleaned,q.cleanup_status AS question_status,
            cs.student_id,cs.requested_name,st.name,c.course_id,c.class_id FROM oral_answers a JOIN oral_questions q ON q.id=a.question_id JOIN classroom_students cs ON cs.session_student_id=a.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id JOIN classroom_sessions s ON s.session_id=a.session_id JOIN classes c ON c.class_id=s.class_id WHERE a.id=?""", (answer_id,)).fetchone()
    else:
        row = c.execute("""SELECT q.*,cs.student_id,cs.requested_name,st.name,c.course_id,c.class_id FROM oral_questions q JOIN classroom_students cs ON cs.session_student_id=q.session_student_id LEFT JOIN class_students st ON st.student_id=cs.student_id JOIN classroom_sessions s ON s.session_id=q.session_id JOIN classes c ON c.class_id=s.class_id WHERE q.id=?""", (question_id,)).fetchone()
    c.close()
    if row is None: raise HTTPException(404, "口述内容不存在。")
    if not get_accounts(request).owns(request.state.account["account_id"], row["course_id"]): raise HTTPException(404, "课程不存在或无权访问。")
    return row


@router.post("/api/oral/questions/{question_id}/optimize")
def optimize_oral_question(question_id: str, request: Request):
    row = _teacher_action(request, question_id=question_id); started = perf_counter()
    from src import web_api
    from src.course_data import CourseStore
    store = CourseStore(get_accounts(request).db_path); runtime = web_api._get_course_runtime(row["course_id"], store)
    try:
        result = runtime.service.question_optimize(row["original_text"], runtime.settings.default_top_k)
        payload = web_api.QuestionOptimizeResponse.model_validate(runtime.source_mapper.sanitize_value(web_api._add_optimized_question_levels(result.data))).model_dump()
    except Exception as error:
        raise web_api._safe_service_error(error) from None
    from src.teaching_history import get_history_store
    get_history_store(store).add(course_id=row["course_id"], task_type="question_optimize", student_id=row["student_id"], class_id=row["class_id"], session_id=row["session_id"], input_data={"question": row["original_text"], "question_cleaned": row["cleaned_text"], "cleanup_status": row["cleanup_status"]}, output_data=payload, duration_ms=round((perf_counter()-started)*1000))
    return payload


@router.post("/api/oral/answers/{answer_id}/evaluate")
def evaluate_oral_answer(answer_id: str, request: Request):
    row = _teacher_action(request, answer_id=answer_id); started = perf_counter()
    try:
        cleaned, status = polish_question(row["original_text"])
    except Exception:
        cleaned, status = row["original_text"], "unformatted"
    if status != "ready" or not validate_cleanup(row["original_text"], cleaned):
        cleaned, status = row["original_text"], "unformatted"
    c = _con(request)
    with c: c.execute("UPDATE oral_answers SET cleaned_text=?,cleanup_status=? WHERE id=?", (cleaned if status == "ready" else row["original_text"], status, answer_id))
    c.close()
    from src import web_api
    from src.course_data import CourseStore
    store = CourseStore(get_accounts(request).db_path); runtime = web_api._get_course_runtime(row["course_id"], store)
    try:
        result = runtime.service.answer_evaluate(row["question_original"], row["original_text"], runtime.settings.default_top_k)
        payload = web_api.AnswerEvaluateResponse.model_validate(runtime.source_mapper.sanitize_value(result.data)).model_dump()
    except Exception as error:
        raise web_api._safe_service_error(error) from None
    from src.teaching_history import get_history_store
    get_history_store(store).add(course_id=row["course_id"], task_type="answer_evaluate", student_id=row["student_id"], class_id=row["class_id"], session_id=row["session_id"], input_data={"question": row["question_original"], "student_answer": row["original_text"], "answer_cleaned": cleaned if status == "ready" else row["original_text"], "cleanup_status": status}, output_data=payload, duration_ms=round((perf_counter()-started)*1000))
    return payload

