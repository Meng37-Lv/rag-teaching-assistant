from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.course_data import CourseCreate, CourseStore
from src.teaching_analytics import calculate_statistics
from src.teaching_history import TeachingHistoryStore


class TeachingAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.tmp.name) / "courses.db")
        self.course = self.store.create(CourseCreate(name="统计课程"))
        self.history = TeachingHistoryStore(self.store.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_statistics_are_deterministic_and_mark_small_sample(self) -> None:
        for task in ("question_optimize", "answer_evaluate", "presentation_questions"):
            self.history.add(course_id=self.course.id, task_type=task, input_data={}, output_data={"course_basis": [{"source": "第1章", "reason": "依据"}], "issues": [{"type": "概念混淆", "description": "问题"}]}, duration_ms=10)
        events, _ = self.history.list(self.course.id, page=1, page_size=100)
        stats = calculate_statistics(events)
        self.assertTrue(stats["data_insufficient"])
        self.assertEqual(stats["sample_size"], 3)
        self.assertEqual(stats["usage_counts"]["question_optimize"], 1)
        self.assertEqual(stats["common_issues"][0]["value"], "概念混淆")
        self.assertEqual(stats["frequent_chapters"][0]["value"], "第1章")

    def test_low_score_points_include_traceable_event_ids(self) -> None:
        event = self.history.add(course_id=self.course.id, task_type="question_optimize", input_data={}, output_data={"question_evaluation": {"score": 70, "level": "简单"}, "course_basis": [{"source": "第2章", "reason": "依据"}]})
        events, _ = self.history.list(self.course.id, page=1, page_size=100)
        points = calculate_statistics(events)["low_score_knowledge_points"]
        self.assertEqual(points[0]["name"], "依据")
        self.assertIn("第2章", points[0]["basis"])


if __name__ == "__main__":
    unittest.main()
