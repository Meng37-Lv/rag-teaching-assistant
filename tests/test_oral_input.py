from __future__ import annotations

import io
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from src.course_data import CourseStore, get_course_store
from src.web_api import app
from tests.auth_helpers import login_test_client


class OralInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = CourseStore(Path(self.tmp.name) / "db.sqlite")
        app.dependency_overrides[get_course_store] = lambda: self.store
        self.client = TestClient(app); login_test_client(self.client, self.store)
        course = self.client.post("/api/courses", json={"name": "口述课程"}).json(); self.course_id = course["id"]
        classroom = self.client.post(f"/api/courses/{course['id']}/classes", json={"name": "口述班"}).json()
        wb = Workbook(); ws = wb.active; ws.append(["姓名", "学号"]); ws.append(["张三", "001"]); ws.append(["李四", "002"])
        out = io.BytesIO(); wb.save(out); out.seek(0)
        self.client.post(f"/api/classes/{classroom['class_id']}/import", files={"file": ("r.xlsx", out.getvalue())})
        self.session = self.client.post(f"/api/classes/{classroom['class_id']}/sessions").json()
        self.a = self.client.post(f"/api/join/{self.session['join_token']}", json={"name": "张三"}).json()
        self.b = self.client.post(f"/api/join/{self.session['join_token']}", json={"name": "李四"}).json()

    def tearDown(self):
        self.client.close(); app.dependency_overrides.clear(); self.tmp.cleanup()

    def h(self, token): return {"X-Student-Session": token}

    def test_drafts_are_private_and_independent(self):
        sid = self.session["session_id"]
        self.assertEqual(self.client.patch(f"/api/sessions/{sid}/oral-drafts", headers=self.h(self.a["student_token"]), json={"kind": "question", "body": "张三草稿"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/sessions/{sid}/oral-drafts", headers=self.h(self.b["student_token"]), json={"kind": "question", "body": "李四草稿"}).status_code, 200)
        own = self.client.get(f"/api/sessions/{sid}/oral-state", headers=self.h(self.a["student_token"])).json()
        self.assertEqual(own["drafts"][0]["body"], "张三草稿")
        teacher = self.client.get(f"/api/sessions/{sid}/oral-drafts").json()
        self.assertEqual({item["body"] for item in teacher}, {"张三草稿", "李四草稿"})

    def test_question_replaces_current_and_answers_bind_to_submission_question(self):
        sid = self.session["session_id"]
        first = self.client.post(f"/api/sessions/{sid}/oral-questions", headers=self.h(self.a["student_token"]), json={"body": "嗯，模型A为什么好？"}).json()
        answer = self.client.post(f"/api/sessions/{sid}/oral-answers", headers=self.h(self.b["student_token"]), json={"body": "回答第一个问题"}).json()
        second = self.client.post(f"/api/sessions/{sid}/oral-questions", headers=self.h(self.a["student_token"]), json={"body": "模型B如何验证？"}).json()
        self.assertNotEqual(first["question_id"], second["question_id"])
        self.assertEqual(answer["question_id"], first["question_id"])
        state = self.client.get(f"/api/sessions/{sid}/oral-state", headers=self.h(self.b["student_token"])).json()
        self.assertEqual(state["current_question"]["question_id"], second["question_id"])
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/oral-answers", headers=self.h(self.b["student_token"]), json={"body": "新的回答"}).status_code, 200)

    def test_no_question_pending_rejected_and_ended_disabled(self):
        sid = self.session["session_id"]
        self.client.post(f"/api/sessions/{sid}/end")
        self.assertEqual(self.client.patch(f"/api/sessions/{sid}/oral-drafts", headers=self.h(self.a["student_token"]), json={"kind": "question", "body": "x"}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/oral-answers", headers=self.h(self.b["student_token"]), json={"body": "x"}).status_code, 409)

    def test_cleanup_failure_keeps_original_and_marks_unformatted(self):
        sid = self.session["session_id"]
        with patch("src.oral_input.polish_question", side_effect=RuntimeError("mock cleanup failure")):
            result = self.client.post(f"/api/sessions/{sid}/oral-questions", headers=self.h(self.a["student_token"]), json={"body": "原话 123"})
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json()["cleanup_status"], "unformatted"); self.assertEqual(result.json()["cleaned_text"], "原话 123")

    def test_cleanup_rejects_new_number(self):
        sid = self.session["session_id"]
        with patch("src.oral_input.polish_question", return_value=("模型A 999", "ready")):
            result = self.client.post(f"/api/sessions/{sid}/oral-questions", headers=self.h(self.a["student_token"]), json={"body": "模型A 123"})
        # The endpoint stores the original whenever a provider claims an invalid cleanup.
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json()["cleanup_status"], "unformatted"); self.assertEqual(result.json()["cleaned_text"], "模型A 123")

    def test_teacher_actions_use_original_and_bound_question_and_write_history(self):
        sid = self.session["session_id"]
        question = self.client.post(f"/api/sessions/{sid}/oral-questions", headers=self.h(self.a["student_token"]), json={"body": "问题原话"}).json()
        answer = self.client.post(f"/api/sessions/{sid}/oral-answers", headers=self.h(self.b["student_token"]), json={"body": "回答原话"}).json()
        class Service:
            def question_optimize(self, text, top_k): return SimpleNamespace(data={"optimized_questions":[{"question":"q1"},{"question":"q2"},{"question":"q3"}], "deep_questions":[], "question_evaluation":{}, "course_basis":[], "insufficiency_notice":""})
            def answer_evaluate(self, question, answer, top_k): return SimpleNamespace(data={"overall_evaluation":"ok", "question":question, "student_answer":answer, "course_basis":[]})
        runtime=SimpleNamespace(service=Service(),settings=SimpleNamespace(default_top_k=3),source_mapper=SimpleNamespace(sanitize_value=lambda x:x))
        import src.web_api as web_api
        class Validated:
            def __init__(self,data): self.data=data
            def model_dump(self): return self.data
        with patch("src.web_api._get_course_runtime", return_value=runtime), patch.object(web_api.QuestionOptimizeResponse,"model_validate", side_effect=lambda value: Validated(value)), patch.object(web_api.AnswerEvaluateResponse,"model_validate", side_effect=lambda value: Validated(value)):
            optimized=self.client.post(f"/api/oral/questions/{question['question_id']}/optimize")
            evaluated=self.client.post(f"/api/oral/answers/{answer['answer_id']}/evaluate")
        self.assertEqual(optimized.status_code,200, optimized.text); self.assertEqual(evaluated.status_code,200, evaluated.text)
        from src.teaching_history import TeachingHistoryStore
        events,_=TeachingHistoryStore(self.store.db_path).list(self.course_id)
        self.assertGreaterEqual(len(events), 2)
        self.assertTrue(any(event.input_json.get("question")=="问题原话" for event in events))


if __name__ == "__main__": unittest.main()
