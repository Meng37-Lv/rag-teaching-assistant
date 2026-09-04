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
