from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import PreviewSettings
from src.preview_converter import PreviewConversionError, convert_to_pdf


class FakeProcess:
    def __init__(self, command, outcome="ok"):
        self.command = command
        self.outcome = outcome
        self.returncode = None
        self.pid = 1234

    def communicate(self, timeout=None):
        if self.outcome == "timeout" and self.returncode is None:
            from subprocess import TimeoutExpired
            self.returncode = -9
            raise TimeoutExpired(self.command, timeout)
        if self.outcome == "nonzero":
            self.returncode = 7
            return "", "converter failed"
        outdir = Path(self.command[self.command.index("--outdir") + 1])
        source = Path(self.command[-1])
        (outdir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.7\nmock")
        self.returncode = 0
        return "convert ok", ""

    def poll(self):
        return self.returncode


class PreviewConverterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "submissions" / "session" / "submission" / "report.pptx"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"pptx bytes")
        self.preview_dir = self.source.parent / "previews"
        self.config = PreviewSettings("soffice", 60, 180, 1, 3600, "", "lo-test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_uses_impress_filter_and_cache(self):
        processes = []

        def popen(command, **kwargs):
            process = FakeProcess(command)
            processes.append(process)
            return process

        with patch("src.preview_converter.shutil.which", return_value="soffice"), patch("src.preview_converter.subprocess.Popen", side_effect=popen):
            first = convert_to_pdf(self.source, self.preview_dir, self.config)
            second = convert_to_pdf(self.source, self.preview_dir, self.config)
        self.assertEqual(first.status, "PREVIEW_OK")
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(len(processes), 1)
        self.assertIn("pdf:impress_pdf_Export", processes[0].command)
        self.assertTrue(first.pdf_path.read_bytes().startswith(b"%PDF-"))

    def test_changed_source_invalidates_cache(self):
        calls = []
        with patch("src.preview_converter.shutil.which", return_value="soffice"), patch("src.preview_converter.subprocess.Popen", side_effect=lambda command, **kwargs: calls.append(FakeProcess(command)) or calls[-1]):
            convert_to_pdf(self.source, self.preview_dir, self.config)
            self.source.write_bytes(b"changed pptx bytes")
            convert_to_pdf(self.source, self.preview_dir, self.config)
        self.assertEqual(len(calls), 2)

    def test_timeout_cleans_temporary_directory(self):
        with patch("src.preview_converter.shutil.which", return_value="soffice"), patch("src.preview_converter.subprocess.Popen", side_effect=lambda command, **kwargs: FakeProcess(command, "timeout")), patch("src.preview_converter.subprocess.run"):
            with self.assertRaisesRegex(PreviewConversionError, "超时") as error:
                convert_to_pdf(self.source, self.preview_dir, self.config)
        self.assertEqual(error.exception.code, "PREVIEW_TIMEOUT")
        self.assertEqual(list(self.preview_dir.glob(".preview-tmp-*")), [])

    def test_nonzero_exit_and_missing_pdf_are_classified(self):
        with patch("src.preview_converter.shutil.which", return_value="soffice"), patch("src.preview_converter.subprocess.Popen", side_effect=lambda command, **kwargs: FakeProcess(command, "nonzero")):
            with self.assertRaisesRegex(PreviewConversionError, "转换失败") as error:
                convert_to_pdf(self.source, self.preview_dir, self.config)
        self.assertEqual(error.exception.code, "PREVIEW_CONVERSION_FAILED")

        class MissingPdf(FakeProcess):
            def communicate(self, timeout=None):
                self.returncode = 0
                return "ok", ""

        with patch("src.preview_converter.shutil.which", return_value="soffice"), patch("src.preview_converter.subprocess.Popen", side_effect=lambda command, **kwargs: MissingPdf(command)):
            with self.assertRaises(PreviewConversionError) as missing:
                convert_to_pdf(self.source, self.preview_dir, self.config)
        self.assertEqual(missing.exception.code, "PREVIEW_CONVERSION_FAILED")


if __name__ == "__main__":
    unittest.main()
