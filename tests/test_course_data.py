from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.course_data import CourseStore, get_course_store
from src.web_api import app


class CourseApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.temp_dir.name) / "courses.db")
        app.dependency_overrides[get_course_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.temp_dir.cleanup()

    def test_create_defaults_status_and_trims_name(self) -> None:
        response = self.client.post("/api/courses", json={"name": "  数学基础  "})
        self.assertEqual(response.status_code, 201)
        course = response.json()
        self.assertEqual(course["name"], "数学基础")
        self.assertEqual(course["status"], "draft")
        self.assertTrue(course["id"])

    def test_field_validation(self) -> None:
        self.assertEqual(self.client.post("/api/courses", json={"name": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/courses", json={"name": "x" * 101}).status_code, 422)
        self.assertEqual(
            self.client.post("/api/courses", json={"name": "课程", "description": "x" * 2001}).status_code,
            422,
        )

    def test_list_and_detail(self) -> None:
        created = self.client.post("/api/courses", json={"name": "课程一"}).json()
        self.client.post("/api/courses", json={"name": "课程二"})
        listed = self.client.get("/api/courses")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 2)
        detail = self.client.get(f"/api/courses/{created['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], created["id"])

    def test_update(self) -> None:
        course = self.client.post("/api/courses", json={"name": "旧名称"}).json()
        response = self.client.patch(
            f"/api/courses/{course['id']}",
            json={"name": " 新名称 ", "status": "ready", "teaching_goal": "目标"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "新名称")
        self.assertEqual(response.json()["status"], "ready")

    def test_delete(self) -> None:
        course = self.client.post("/api/courses", json={"name": "待删除"}).json()
        self.assertEqual(self.client.delete(f"/api/courses/{course['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/courses/{course['id']}").status_code, 404)

    def test_invalid_id_and_status(self) -> None:
        self.assertEqual(self.client.get("/api/courses/not-found").status_code, 404)
        self.assertEqual(self.client.patch("/api/courses/not-found", json={"status": "draft"}).status_code, 404)
        course = self.client.post("/api/courses", json={"name": "课程"}).json()
        self.assertEqual(self.client.patch(f"/api/courses/{course['id']}", json={"status": "invalid"}).status_code, 422)

    def test_delete_keeps_association_check_extensible(self) -> None:
        course = self.client.post("/api/courses", json={"name": "有关联"}).json()
        self.store.has_materials = lambda _course_id: True  # type: ignore[method-assign]
        response = self.client.delete(f"/api/courses/{course['id']}")
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
