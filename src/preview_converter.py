from __future__ import annotations

import hashlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import PreviewSettings


logger = logging.getLogger(__name__)


class PreviewConversionError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class PreviewResult:
    status: str
    pdf_path: Path
    cache_key: str
    converter_version: str
    cache_hit: bool


_semaphore_lock = threading.Lock()
_semaphores: dict[int, threading.BoundedSemaphore] = {}
_cache_lock = threading.RLock()
_conversion_locks: dict[str, threading.Lock] = {}


def _semaphore(limit: int) -> threading.BoundedSemaphore:
    with _semaphore_lock:
        return _semaphores.setdefault(limit, threading.BoundedSemaphore(limit))


def _resolve_executable(configured: str) -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_dir():
        candidate = candidate / ("program/soffice.exe" if os.name == "nt" else "program/soffice")
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise PreviewConversionError("PREVIEW_CONVERTER_UNAVAILABLE", "本地预览转换器不可用，请联系管理员配置 LibreOffice。", status_code=503)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except PermissionError as error:
        raise PreviewConversionError("PREVIEW_PERMISSION_DENIED", "没有权限读取原文件。", status_code=403) from error
    return digest.hexdigest()


def _font_hash(font_dir: str) -> str:
    if not font_dir:
        return "system-fonts"
    root = Path(font_dir).expanduser()
    if not root.is_dir():
        return "missing-font-dir"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(f"{path.relative_to(root)}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8", "replace"))
    return digest.hexdigest()[:16]


def _safe_version(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return cleaned[:80] or "unknown"


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            process.kill()


def _is_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size < 5:
            return False
        with path.open("rb") as stream:
            return stream.read(5) == b"%PDF-"
    except OSError:
        return False


def cleanup_preview_artifacts(submissions_root: Path, ttl_seconds: int) -> None:
    """Remove expired temporary files and orphaned preview PDFs only."""
    if not submissions_root.is_dir():
        return
    cutoff = time.time() - ttl_seconds
    for preview_dir in submissions_root.glob("*/*/previews"):
        if not preview_dir.is_dir():
            continue
        submission_dir = preview_dir.parent
        originals = [item for item in submission_dir.iterdir() if item.is_file() and item.suffix.lower() != ".pdf"]
        for item in list(preview_dir.iterdir()):
            try:
                if item.is_dir() and item.name.startswith(".preview-tmp-"):
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file() and (item.stat().st_mtime < cutoff or not originals):
                    item.unlink(missing_ok=True)
            except OSError:
                logger.info("preview_cleanup_failed type=file")


def convert_to_pdf(input_path: Path, preview_dir: Path, config: PreviewSettings, *, total_timeout_seconds: float | None = None) -> PreviewResult:
    if not input_path.is_file():
        raise PreviewConversionError("PREVIEW_FILE_NOT_FOUND", "原文件不存在，无法生成预览。", status_code=404)
    suffix = input_path.suffix.lower()
    if suffix not in {".pptx", ".docx"}:
        raise PreviewConversionError("PREVIEW_CONVERSION_FAILED", "仅支持 PPTX 和 DOCX 转换为 PDF。")

    preview_dir.mkdir(parents=True, exist_ok=True)
    cleanup_preview_artifacts(preview_dir.parents[2], config.cache_ttl_seconds)
    converter = _resolve_executable(config.converter_path)
    content_hash = _hash_file(input_path)
    font_hash = _font_hash(config.font_dir)
    converter_version = _safe_version(config.converter_version)
    target = "impress_pdf_Export" if suffix == ".pptx" else "writer_pdf_Export"
    cache_key = hashlib.sha256(f"{content_hash}:{converter_version}:{font_hash}:{target}".encode()).hexdigest()
    output_path = preview_dir / f"{content_hash[:32]}-{converter_version}-{font_hash}-{target}.pdf"
    with _cache_lock:
        key_lock = _conversion_locks.setdefault(str(output_path), threading.Lock())
    key_lock.acquire()
    try:
        with _cache_lock:
            if _is_pdf(output_path):
                return PreviewResult("PREVIEW_OK", output_path, cache_key, converter_version, True)

        semaphore = _semaphore(config.max_concurrency)
        overall_started = time.monotonic()
        total_timeout = total_timeout_seconds or config.submission_timeout_seconds
        acquired = semaphore.acquire(timeout=total_timeout)
        if not acquired:
            raise PreviewConversionError("PREVIEW_TIMEOUT", "预览转换排队超时，请稍后重试。", status_code=504)
        started = time.monotonic()
        temp_root: Path | None = None
        process: subprocess.Popen[str] | None = None
        try:
            with _cache_lock:
                if _is_pdf(output_path):
                    return PreviewResult("PREVIEW_OK", output_path, cache_key, converter_version, True)
            # LibreOffice on Windows can silently produce no output when its
            # input file and output/profile directories are nested under the
            # same submission directory. Use the OS temporary area for the
            # active conversion, then atomically move the PDF into the
            # submission-scoped cache after conversion succeeds.
            temp_root = Path(tempfile.mkdtemp(prefix=".preview-tmp-"))
            out_dir = temp_root / "out"
            profile_dir = temp_root / "profile"
            out_dir.mkdir()
            profile_dir.mkdir()
            profile_uri = profile_dir.resolve().as_uri()
            command = [
                converter,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                f"pdf:{target}",
                "--outdir",
                str(out_dir),
                str(input_path),
            ]
            converter_environment = os.environ.copy()
            if config.font_dir and Path(config.font_dir).is_dir():
                # LibreOffice's private-font hook keeps bundled fonts local to the
                # conversion process; no system font installation is performed.
                converter_environment["SAL_PRIVATE_FONTS"] = str(Path(config.font_dir).resolve())
            kwargs: dict[str, object] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace", "env": converter_environment}
            if os.name != "nt":
                kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
            remaining = total_timeout - (time.monotonic() - overall_started)
            if remaining <= 0:
                raise PreviewConversionError("PREVIEW_TIMEOUT", "预览转换总时限已到，请稍后重试。", status_code=504)
            timeout = min(config.file_timeout_seconds, remaining)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process_tree(process)
                process.communicate()
                logger.warning("preview_convert type=timeout bytes=%s hash=%s", input_path.stat().st_size, content_hash[:16])
                raise PreviewConversionError("PREVIEW_TIMEOUT", "预览转换超时，请稍后重试。", status_code=504) from None
            if process.returncode != 0:
                logger.warning("preview_convert type=exit_nonzero code=%s hash=%s stderr=%s", process.returncode, content_hash[:16], (stderr or "")[:160].replace("\n", " "))
                raise PreviewConversionError("PREVIEW_CONVERSION_FAILED", "原格式预览转换失败，请下载原文件查看。")
            expected_candidate = out_dir / f"{input_path.stem}.pdf"
            candidates = [item for item in out_dir.glob("*.pdf") if item.is_file()]
            candidate = expected_candidate if expected_candidate.is_file() else candidates[0] if len(candidates) == 1 else None
            if candidate is None or not _is_pdf(candidate):
                logger.warning("preview_convert type=missing_pdf hash=%s stdout=%s", content_hash[:16], (stdout or "")[:160].replace("\n", " "))
                raise PreviewConversionError("PREVIEW_CONVERSION_FAILED", "预览转换未生成有效 PDF，请下载原文件查看。")
            with _cache_lock:
                os.replace(candidate, output_path)
            logger.info("preview_convert type=success bytes=%s hash=%s elapsed_ms=%s", input_path.stat().st_size, content_hash[:16], round((time.monotonic() - started) * 1000))
            return PreviewResult("PREVIEW_OK", output_path, cache_key, converter_version, False)
        except PreviewConversionError:
            raise
        except PermissionError as error:
            raise PreviewConversionError("PREVIEW_PERMISSION_DENIED", "预览文件写入权限不足。", status_code=403) from error
        except OSError as error:
            raise PreviewConversionError("PREVIEW_CONVERSION_FAILED", "预览转换失败，请下载原文件查看。") from error
        finally:
            if process is not None and process.poll() is None:
                _kill_process_tree(process)
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)
            semaphore.release()
    finally:
        key_lock.release()
