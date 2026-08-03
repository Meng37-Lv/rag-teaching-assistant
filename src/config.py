from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    """表示项目配置不完整或不合法。"""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"缺少 {name}，请在 .env 中填写有效值。")
    return value


def _positive_int(name: str, default: int) -> int:
    text = os.getenv(name, str(default)).strip()
    try:
        value = int(text)
    except ValueError as error:
        raise ConfigError(f"{name} 必须是整数。") from error
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0。")
    return value


def _positive_float(name: str, default: float) -> float:
    text = os.getenv(name, str(default)).strip()
    try:
        value = float(text)
    except ValueError as error:
        raise ConfigError(f"{name} 必须是数字。") from error
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0。")
    return value


def _boolean(name: str, default: bool) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    enable_thinking: bool
    timeout_seconds: float
    default_top_k: int
    max_context_chars: int
    max_chunk_chars: int


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        api_key=_required("LLM_API_KEY"),
        base_url=_required("LLM_BASE_URL").rstrip("/"),
        model=_required("LLM_MODEL"),
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "high").strip() or "high",
        enable_thinking=_boolean("LLM_ENABLE_THINKING", True),
        timeout_seconds=_positive_float("LLM_TIMEOUT_SECONDS", 12),
        default_top_k=_positive_int("RAG_TOP_K", 3),
        max_context_chars=_positive_int("RAG_MAX_CONTEXT_CHARS", 1800),
        max_chunk_chars=_positive_int("RAG_MAX_CHUNK_CHARS", 600),
    )
