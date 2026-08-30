from __future__ import annotations

import json
import unittest

from src.config import Settings
from src.llm_client import LLMCompletion
from src.material_parser import parse_text_material
from src.report_question_service import ReportQuestionService, validate_report_questions


def _valid_output() -> dict[str, object]:
    level_specs = [
        ("easy", "简单", 60),
        ("medium", "中等", 80),
        ("hard", "困难", 100),
    ]
    return {
        "questions": [
            {
                "level": level,
                "label": label,
                "score": score,
                "question": f"在{label}层级，材料中的两个核心功能为何采用第{angle}种设计思路？",
            }
            for level, label, score in level_specs
            for angle in range(1, 4)
        ]
    }


class FakeLLMClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LLMCompletion:
        content = self.contents[self.calls]
        self.calls += 1
        return LLMCompletion(content, "stop", 100, max_tokens)


class ReportQuestionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="test",
            base_url="https://example.invalid",
            model="test",
            reasoning_effort="high",
            enable_thinking=False,
            timeout_seconds=12,
            default_top_k=3,
            max_context_chars=1800,
            max_chunk_chars=600,
        )
        self.material = parse_text_material("材料介绍系统目标和两个核心功能。", "测试材料")

    def test_valid_three_questions_per_level_output(self) -> None:
        fake = FakeLLMClient([json.dumps(_valid_output(), ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(self.material)

        self.assertFalse(result.retried)
        self.assertEqual(
            [item["score"] for item in result.data["questions"]],
            [60, 60, 60, 80, 80, 80, 100, 100, 100],
        )

    def test_invalid_output_retries_only_once(self) -> None:
        invalid = _valid_output()
        invalid["questions"][0]["score"] = 50
        fake = FakeLLMClient(
            [
                json.dumps(invalid, ensure_ascii=False),
                json.dumps(_valid_output(), ensure_ascii=False),
            ]
        )

        result = ReportQuestionService(self.settings, fake).generate(self.material)

        self.assertTrue(result.retried)
        self.assertEqual(fake.calls, 2)

    def test_rejects_memory_question(self) -> None:
        invalid = _valid_output()
        invalid["questions"][0]["question"] = "材料使用哪个数据集？"

        with self.assertRaisesRegex(ValueError, "纯记忆型问法"):
            validate_report_questions(invalid)

    def test_rejects_fewer_than_three_questions_in_a_level(self) -> None:
        invalid = _valid_output()
        invalid["questions"] = invalid["questions"][:8]
        with self.assertRaisesRegex(ValueError, "恰好包含9项"):
            validate_report_questions(invalid)

    def test_rejects_duplicate_angles(self) -> None:
        invalid = _valid_output()
        invalid["questions"][1]["question"] = invalid["questions"][0]["question"]
        with self.assertRaisesRegex(ValueError, "考查不同角度"):
            validate_report_questions(invalid)


if __name__ == "__main__":
    unittest.main()
