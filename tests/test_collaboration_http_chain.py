from __future__ import annotations

import io
import gc
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from src.course_data import CourseStore, get_course_store
from src.web_api import app
from tests.auth_helpers import login_test_client
from tests.test_report_question_service import grounded_output


class _TeachingService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def question_optimize(self, question: str, top_k: int):
        self.calls.append(("question_optimize", question))
        return SimpleNamespace(data={
            "optimized_questions": [{"question": "优化问题一"}, {"question": "优化问题二"}, {"question": "优化问题三"}],
            "deep_questions": [], "question_evaluation": {}, "course_basis": [], "insufficiency_notice": "",
        })

    def answer_evaluate(self, question: str, answer: str, top_k: int):
        self.calls.append(("answer_evaluate", question, answer))
        return SimpleNamespace(data={"overall_evaluation": "评价完成", "question": question, "student_answer": answer, "course_basis": []})


class _ReportQuestionService:
    def __init__(self) -> None:
        self.materials = []

    def generate(self, material, instruction=None):
        self.materials.append(material)
        return SimpleNamespace(data=grounded_output(material))


class CollaborationHttpChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("RAG_APP_DATA_DIR")
        os.environ["RAG_APP_DATA_DIR"] = self.tmp.name
        self.store = CourseStore(Path(self.tmp.name) / "db.sqlite")
        app.dependency_overrides[get_course_store] = lambda: self.store
        self.client = TestClient(app)
        login_test_client(self.client, self.store)
        course = self.client.post("/api/courses", json={"name": "协作 HTTP 测试课程"}).json()
        classroom = self.client.post(f"/api/courses/{course['id']}/classes", json={"name": "协作班"}).json()
        roster = Workbook(); sheet = roster.active
        sheet.append(["姓名", "学号"]); sheet.append(["张三", "001"]); sheet.append(["李四", "002"])
        content = io.BytesIO(); roster.save(content); content.seek(0)
        self.client.post(f"/api/classes/{classroom['class_id']}/import", files={"file": ("roster.xlsx", content.getvalue())})
        self.session = self.client.post(f"/api/classes/{classroom['class_id']}/sessions").json()
        self.course_id = course["id"]; self.class_id = classroom["class_id"]
        self.students = {}
        for name in ("张三", "李四"):
            joined = self.client.post(f"/api/join/{self.session['join_token']}", json={"name": name}).json()
            self.students[name] = {"X-Student-Session": joined["student_token"]}

    def tearDown(self) -> None:
        app.dependency_overrides.clear(); self.client.close(); gc.collect(); self.tmp.cleanup()
        if self.old_data_dir is None: os.environ.pop("RAG_APP_DATA_DIR", None)
        else: os.environ["RAG_APP_DATA_DIR"] = self.old_data_dir

    def round(self, feature: str, snapshot: str | None = None) -> dict:
        payload = {"class_id": self.class_id, "session_id": self.session["session_id"], "feature_type": feature}
        if snapshot is not None: payload["question_snapshot"] = snapshot
        response = self.client.post("/api/collaboration/rounds", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def claim_and_accept(self, round_data: dict, student: str = "张三") -> tuple[str, dict]:
        headers = self.students[student]
        claim = self.client.post(f"/api/collaboration/tokens/{round_data['round_token']}/claim", headers=headers)
        self.assertEqual(claim.status_code, 200, claim.text)
        claim_id = claim.json()["claim_id"]
        accepted = self.client.post(f"/api/collaboration/claims/{claim_id}/accept")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        return claim_id, headers

    def test_question_http_chain_writes_bound_history(self) -> None:
        runtime = SimpleNamespace(service=_TeachingService(), settings=SimpleNamespace(default_top_k=3), source_mapper=SimpleNamespace(sanitize_value=lambda value: value))
        with patch("src.web_api._get_course_runtime", return_value=runtime), patch("src.web_api.QuestionOptimizeResponse.model_validate", side_effect=lambda value: SimpleNamespace(model_dump=lambda: value)):
            round_data = self.round("question_optimize")
            claim_id, headers = self.claim_and_accept(round_data)
            self.assertEqual(self.client.patch(f"/api/collaboration/claims/{claim_id}/entry", headers=headers, json={"text": "学生原问题"}).status_code, 200)
            self.assertEqual(self.client.post(f"/api/collaboration/claims/{claim_id}/complete", headers=headers).status_code, 200)
            self.assertEqual(self.client.patch(f"/api/collaboration/rounds/{round_data['round_id']}/teacher-entry", json={"text": "教师最终问题"}).status_code, 200)
            self.assertEqual(self.client.post(f"/api/collaboration/rounds/{round_data['round_id']}/submit").status_code, 200)
        with sqlite3.connect(self.store.db_path) as connection:
            row = connection.execute("SELECT class_id,session_id,student_id,round_id,input_json FROM teaching_events WHERE round_id=?", (round_data["round_id"],)).fetchone()
        self.assertIsNotNone(row); self.assertEqual(row[0], self.class_id); self.assertEqual(row[1], self.session["session_id"]); self.assertTrue(row[2]); self.assertEqual(row[3], round_data["round_id"]); self.assertIn("教师最终问题", row[4])

    def test_answer_snapshot_is_read_only_and_old_round_cannot_cross(self) -> None:
        runtime = SimpleNamespace(service=_TeachingService(), settings=SimpleNamespace(default_top_k=3), source_mapper=SimpleNamespace(sanitize_value=lambda value: value))
        with patch("src.web_api._get_course_runtime", return_value=runtime), patch("src.web_api.AnswerEvaluateResponse.model_validate", side_effect=lambda value: SimpleNamespace(model_dump=lambda: value)):
            old_round = self.round("answer_evaluate", "旧题目")
            claim_id, headers = self.claim_and_accept(old_round)
            state = self.client.get(f"/api/collaboration/rounds/{old_round['round_id']}/student-state", headers=headers).json()
            self.assertEqual(state["question_snapshot"], "旧题目")
            self.client.patch(f"/api/collaboration/claims/{claim_id}/entry", headers=headers, json={"text": "学生试图改题", "answer": "旧题答案"})
            self.client.post(f"/api/collaboration/claims/{claim_id}/complete", headers=headers)
            self.assertEqual(self.client.post(f"/api/collaboration/rounds/{old_round['round_id']}/submit").status_code, 200)
            self.assertEqual(runtime.service.calls[-1][1], "旧题目")
            self.assertEqual(self.client.post(f"/api/collaboration/rounds/{old_round['round_id']}/cancel").status_code, 200)
            new_round = self.round("answer_evaluate", "新题目")
            self.assertNotEqual(old_round["round_id"], new_round["round_id"])
            self.assertEqual(self.client.get(f"/api/collaboration/rounds/{old_round['round_id']}/student-state", headers=headers).json()["question_snapshot"], "旧题目")
            self.assertEqual(self.client.post(f"/api/collaboration/rounds/{old_round['round_id']}/submit").status_code, 409)

    def test_presentation_round_aggregates_files_and_isolates_old_round(self) -> None:
        round_data = self.round("presentation_questions")
        claim_id, headers = self.claim_and_accept(round_data)
        upload = self.client.post(f"/api/sessions/{self.session['session_id']}/submissions", headers=headers, data={"round_id": round_data["round_id"]}, files=[("files", ("a.txt", b"material-a", "text/plain")), ("files", ("b.txt", b"material-b", "text/plain"))])
        self.assertEqual(upload.status_code, 200, upload.text)
        self.client.post(f"/api/collaboration/claims/{claim_id}/complete", headers=headers)
        self.client.headers.pop("X-Student-Session", None)
        question_service = _ReportQuestionService()
        with patch("src.submissions._get_submission_question_service", return_value=question_service):
            file_id = upload.json()["files"][0]["file_id"]
            self.assertEqual(self.client.get(f"/api/submission-files/{file_id}/preview").status_code, 200)
            self.assertEqual(self.client.get(f"/api/submission-files/{file_id}/content").status_code, 200)
            generated = self.client.post(f"/api/submission-files/{file_id}/generate-question")
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(len(question_service.materials), 1); self.assertEqual(len(question_service.materials[0].segments), 2)
        self.assertIn("a.txt", question_service.materials[0].material_name); self.assertIn("b.txt", question_service.materials[0].material_name)

    def test_concurrency_expiry_and_upload_rollback(self) -> None:
        round_data = self.round("presentation_questions")
        first = self.client.post(f"/api/collaboration/tokens/{round_data['round_token']}/claim", headers=self.students["张三"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post(f"/api/collaboration/tokens/{round_data['round_token']}/claim", headers=self.students["李四"]).status_code, 409)
        expired = self.round("question_optimize")
        os.environ["COLLABORATION_TIMEOUT_SECONDS"] = "0"
        try: self.assertEqual(self.client.post(f"/api/collaboration/tokens/{expired['round_token']}/claim", headers=self.students["张三"]).status_code, 409)
        finally: os.environ.pop("COLLABORATION_TIMEOUT_SECONDS", None)
        with sqlite3.connect(self.store.db_path) as connection: before = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        failed = self.client.post(f"/api/sessions/{self.session['session_id']}/submissions", headers=self.students["张三"], files={"files": ("broken.pptx", b"not-a-pptx", "application/octet-stream")})
        self.assertEqual(failed.status_code, 400)
        with sqlite3.connect(self.store.db_path) as connection: after = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

