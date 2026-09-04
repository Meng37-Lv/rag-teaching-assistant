from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.course_data import CourseCreate, CourseStore
from src.course_materials import CourseMaterialService


class CourseMaterialServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CourseStore(Path(self.temp_dir.name) / "courses.db")
        self.course = self.store.create(CourseCreate(name="测试课程"))
        self.service = CourseMaterialService(self.store, Path(self.temp_dir.name) / "courses")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def upload(filename: str, content: bytes):
        return SimpleNamespace(filename=filename, file=io.BytesIO(content))

    def test_format_and_size_validation(self) -> None:
        with self.assertRaisesRegex(Exception, "仅支持"):
            self.service.upload(self.course.id, self.upload("bad.xls", b"x"))
        pdf = self.service.upload(self.course.id, self.upload("empty.pdf", b"not-a-pdf"))
        self.assertTrue(pdf.id)
        with self.assertRaisesRegex(Exception, "100MB"):
            self.service.upload(self.course.id, self.upload("big.txt", b"x" * (100 * 1024 * 1024 + 1)))

    def test_upload_list_delete_and_ready_resets_to_draft(self) -> None:
        material = self.service.upload(self.course.id, self.upload("a.txt", "课程内容".encode()))
        self.assertEqual(len(self.service.list_materials(self.course.id)), 1)
        course_dir = self.service._course_dir(self.course.id)
        extracted = course_dir / "extracted" / f"{material.id}__a.txt"
        extracted.parent.mkdir(parents=True)
        extracted.write_text("已提取", encoding="utf-8")
        vector_dir = course_dir / "vector_db"
        vector_dir.mkdir(parents=True)
        (vector_dir / "source_mapping.json").write_text("{}", encoding="utf-8")
        self.store.set_status(self.course.id, "ready")
        self.service.delete(self.course.id, material.id)
        self.assertEqual(self.store.get(self.course.id).status, "draft")
        self.assertFalse(extracted.exists())
        self.assertFalse(vector_dir.exists())

    def test_build_without_materials_fails_with_reason(self) -> None:
        result = self.service.build(self.course.id)
        self.assertEqual(result.status, "failed")
        self.assertIn("至少需要一份资料", result.error or "")

    def test_build_status_and_duplicate_build(self) -> None:
        self.service.upload(self.course.id, self.upload("a.txt", "有效课程文本".encode()))
        self.service._lock(self.course.id).acquire()
        try:
            with self.assertRaisesRegex(Exception, "重复构建"):
                self.service.build(self.course.id)
        finally:
            self.service._lock(self.course.id).release()

    def test_single_bad_file_does_not_prevent_valid_file(self) -> None:
        self.service.upload(self.course.id, self.upload("bad.txt", b""))
        self.service.upload(self.course.id, self.upload("good.txt", "有效课程文本".encode()))
        fake_index = object()
        with patch("src.course_materials.encode_chunks", return_value=__import__("numpy").zeros((1, 2), dtype="float32")), \
             patch("src.course_materials.build_index", return_value=fake_index), \
             patch("src.course_materials.save_faiss_index"), \
             patch("src.course_materials.save_chunks_mapping"):
            result = self.service.build(self.course.id)
        self.assertEqual(result.status, "ready")
        self.assertIn("bad.txt", result.error or "")

    def test_preset_course_materials_are_read_only(self) -> None:
        preset = self.store.get("default")
        with self.assertRaisesRegex(Exception, "预置课程资料不可修改"):
            self.service.upload(preset.id, self.upload("a.txt", b"x"))
        with self.assertRaisesRegex(Exception, "预置课程资料不可修改"):
            self.service.build(preset.id)


if __name__ == "__main__":
    unittest.main()
