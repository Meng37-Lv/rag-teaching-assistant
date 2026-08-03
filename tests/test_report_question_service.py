from __future__ import annotations

import json
import unittest

from src.config import Settings
from src.llm_client import LLMCompletion
from src.material_parser import parse_text_material
from src.report_question_service import ReportQuestionService, validate_report_questions


def _valid_output() -> dict[str, object]:
    return {
        "questions": [
            {
                "level": "easy",
                "label": "简单",
                "score": 60,
                "question": "为何选择材料中的两个核心功能，而不是只实现其中一个？",
            },
            {
                "level": "medium",
                "label": "中等",
                "score": 80,
                "question": "两个核心功能协同时可能产生何种偏差，如何验证可靠性？",
            },
            {
                "level": "hard",
                "label": "困难",
                "score": 100,
                "question": "若系统落地受成本限制，应如何设计可验证的改进方案？",
            },
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

    def test_valid_three_level_output(self) -> None:
        fake = FakeLLMClient([json.dumps(_valid_output(), ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(self.material)

        self.assertFalse(result.retried)
        self.assertEqual([item["score"] for item in result.data["questions"]], [60, 80, 100])

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


if __name__ == "__main__":
    unittest.main()
