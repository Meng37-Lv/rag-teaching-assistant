from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.course_data import CourseCreate, CourseStore, get_course_store
from src.teaching_history import TeachingHistoryStore, get_history_store
from src.web_api import app


class TeachingHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.tmp.name) / "courses.db")
        self.course = self.store.create(CourseCreate(name="历史课程"))
        self.other = self.store.create(CourseCreate(name="其他课程"))
        self.history = TeachingHistoryStore(self.store.db_path)
        app.dependency_overrides[get_course_store] = lambda: self.store
        app.dependency_overrides[get_history_store] = lambda: self.history
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.tmp.cleanup()

    def add(self, course_id: str, task_type: str) -> str:
        return self.history.add(course_id=course_id, task_type=task_type, input_data={"question": "问题"}, output_data={"task_type": task_type, "course_basis": []}, duration_ms=12).id

    def test_success_events_and_course_isolation(self) -> None:
        for task in ("question_optimize", "answer_evaluate", "presentation_questions"):
            self.add(self.course.id, task)
        self.add(self.other.id, "question_optimize")
        response = self.client.get(f"/api/courses/{self.course.id}/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)

    def test_filter_pagination_detail_delete_clear_and_csv(self) -> None:
        ids = [self.add(self.course.id, "question_optimize"), self.add(self.course.id, "answer_evaluate"), self.add(self.course.id, "question_optimize")]
        listed = self.client.get(f"/api/courses/{self.course.id}/history", params={"task_type": "question_optimize", "page": 1, "page_size": 1})
        self.assertEqual(listed.json()["total"], 2)
        self.assertEqual(len(listed.json()["items"]), 1)
        self.assertEqual(self.client.get(f"/api/courses/{self.course.id}/history/{ids[0]}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/courses/{self.course.id}/history/{ids[0]}").status_code, 204)
        csv_response = self.client.get(f"/api/courses/{self.course.id}/history/export.csv", params={"task_type": "answer_evaluate"})
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("答案评价", csv_response.text)
        self.assertIn("问题/输入", csv_response.text)
        self.assertNotIn("input_json", csv_response.text)
        cleared = self.client.delete(f"/api/courses/{self.course.id}/history")
        self.assertEqual(cleared.json()["deleted"], 2)
        self.assertEqual(self.client.get(f"/api/courses/{self.course.id}/history").json()["total"], 0)
        empty_export = self.client.get(f"/api/courses/{self.course.id}/history/export.csv")
        self.assertEqual(empty_export.status_code, 404)
        self.assertEqual(empty_export.json()["detail"], "暂无可导出历史")

    def test_missing_course_returns_404(self) -> None:
        self.assertEqual(self.client.get("/api/courses/missing/history").status_code, 404)
        self.assertEqual(self.client.delete("/api/courses/missing/history").status_code, 404)


if __name__ == "__main__":
    unittest.main()
