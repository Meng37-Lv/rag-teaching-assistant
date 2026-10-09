from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def storage_root() -> Path:
    configured = os.getenv("RAG_APP_DATA_DIR", "").strip()
    root = Path(configured).expanduser() if configured else PROJECT_ROOT / "storage"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def course_directory(course_id: str) -> Path:
    root = (storage_root() / "courses").resolve()
    target = (root / course_id).resolve()
    if target.parent != root:
        raise ValueError("课程数据目录无效")
    return target


def submission_directory(session_id: str, submission_id: str) -> Path:
    """Return an isolated directory for one classroom submission."""
    root = (storage_root() / "submissions").resolve()
    target = (root / session_id / submission_id).resolve()
    if root not in target.parents or any(value in {"", ".", ".."} for value in (session_id, submission_id)):
        raise ValueError("提交数据目录无效")
    return target


def get_submission_preview_dir(session_id: str, submission_id: str) -> Path:
    """Return the cache directory used only for rendered preview PDFs."""
    target = (submission_directory(session_id, submission_id) / "previews").resolve()
    submission_root = (storage_root() / "submissions").resolve()
    if submission_root not in target.parents:
        raise ValueError("提交预览目录无效")
    target.mkdir(parents=True, exist_ok=True)
    return target
