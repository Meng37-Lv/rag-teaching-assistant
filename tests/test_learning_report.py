from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.course_data import CourseCreate, CourseStore, get_course_store
from src.teaching_history import TeachingHistoryStore, get_history_store
from src.web_api import app


VALID_REPORT = {name: [{"conclusion": f"{name}结论", "evidence": "统计记录10条，event_id abc"}] for name in ("整体概况", "高频疑点", "常见误区", "薄弱知识点", "思维能力", "代表证据", "教学建议")}


class LearningReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.tmp.name) / "db.sqlite")
        self.course = self.store.create(CourseCreate(name="报告课程"))
        self.history = TeachingHistoryStore(self.store.db_path)
        app.dependency_overrides[get_course_store] = lambda: self.store
        app.dependency_overrides[get_history_store] = lambda: self.history
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def add_records(self, count: int) -> None:
        for _ in range(count):
            self.history.add(course_id=self.course.id, task_type="question_optimize", input_data={"question": "问题"}, output_data={"question_evaluation": {"score": 70, "level": "简单"}, "course_basis": [{"source": "第1章", "reason": "依据"}]})

    def test_small_sample_does_not_call_model(self) -> None:
        self.add_records(9)
        with patch("src.learning_report.LLMClient") as client:
            response = self.client.post(f"/api/courses/{self.course.id}/learning-report", json={})
            self.assertEqual(response.status_code, 400)
            client.assert_not_called()

    def test_report_uses_stats_and_fixed_sections(self) -> None:
        self.add_records(10)
        fake = SimpleNamespace(complete=lambda messages, max_tokens: SimpleNamespace(content=__import__("json").dumps(VALID_REPORT, ensure_ascii=False)))
        with patch("src.learning_report.LLMClient", return_value=fake):
            response = self.client.post(f"/api/courses/{self.course.id}/learning-report", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["record_count"], 10)
        self.assertEqual(set(response.json()["report"]), set(VALID_REPORT))


if __name__ == "__main__":
    unittest.main()
