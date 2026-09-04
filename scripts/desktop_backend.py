from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware


_FALLBACK_STREAMS: list[io.TextIOBase] = []


def _runtime_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root).resolve()
    return Path(__file__).resolve().parents[1]


def _configure_runtime(root: Path) -> None:
    load_dotenv(root / ".env", override=True)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        data_directory = Path(local_app_data) / "课程知识增强教学助手" / "data"
    else:
        data_directory = Path.home() / "AppData" / "Local" / "课程知识增强教学助手" / "data"
    data_directory.mkdir(parents=True, exist_ok=True)
    os.environ["RAG_APP_DATA_DIR"] = str(data_directory.resolve())

    bundled_model_cache = root / "model_cache"
    if bundled_model_cache.is_dir():
        os.environ["HF_HOME"] = str(bundled_model_cache)
        os.environ["HF_HUB_CACHE"] = str(bundled_model_cache / "hub")
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(bundled_model_cache / "hub")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _configure_logging() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        log_directory = Path(local_app_data) / "课程知识增强教学助手" / "logs"
    else:
        log_directory = Path.home() / "AppData" / "Local" / "课程知识增强教学助手" / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "desktop-backend.log"

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and callable(getattr(stream, "isatty", None)):
            continue

        original_stream = getattr(sys, f"__{stream_name}__", None)
        if original_stream is not None and callable(getattr(original_stream, "isatty", None)):
            setattr(sys, stream_name, original_stream)
            continue

        fallback_stream = io.StringIO()
        _FALLBACK_STREAMS.append(fallback_stream)
        setattr(sys, stream_name, fallback_stream)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    logging.captureWarnings(True)
    return log_path


def main() -> None:
    log_path = _configure_logging()
    parser = argparse.ArgumentParser(description="课程知识增强教学助手桌面后端")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    root = _runtime_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    _configure_runtime(root)

    from src.web_api import app

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    import uvicorn

    logging.getLogger(__name__).info(
        "Starting desktop backend on 127.0.0.1:%s; log file: %s",
        args.port,
        log_path,
    )

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=True,
        log_config=None,
    )


if __name__ == "__main__":
    main()
