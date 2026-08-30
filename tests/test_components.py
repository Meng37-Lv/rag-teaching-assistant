from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.rag_service import parse_json_output, validate_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def valid_question_data() -> dict[str, object]:
    return {
        "task_type": "question_optimize",
        "original_question": "什么是深度学习？",
        "question_evaluation": {
            "score": 68,
            "level": "简单",
            "evaluation": "该问题属于概念识别类，范围较宽且主要要求定义复述。",
            "suggestion": "可限定课程场景，并加入机制或应用条件的追问。",
        },
        "optimized_questions": [
            {"question": f"优化问题{i}", "improvement_focus": "改进方向"}
            for i in range(1, 4)
        ],
        "deep_questions": [
            {"question": f"深度问题{i}", "thinking_dimension": "机制分析"}
            for i in range(1, 3)
        ],
        "course_basis": [{"source": "第270页", "reason": "包含深度学习定义"}],
        "insufficiency_notice": "",
    }


class ComponentTests(unittest.TestCase):
    def test_cases_file_has_four_valid_modes(self) -> None:
        cases = json.loads((PROJECT_ROOT / "tests" / "test_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 4)
        self.assertEqual(
            {case["mode"] for case in cases},
            {"question_optimize", "answer_evaluate"},
        )

    def test_direct_json_parse_and_validation(self) -> None:
        data = valid_question_data()
        parsed = parse_json_output(json.dumps(data, ensure_ascii=False))
        validate_output(parsed, "question_optimize", ["第270页"])

    def test_markdown_json_code_block_fallback(self) -> None:
        raw = "```json\n" + json.dumps(valid_question_data(), ensure_ascii=False) + "\n```"
        parsed = parse_json_output(raw)
        self.assertEqual(parsed["task_type"], "question_optimize")

    def test_rejects_unretrieved_source(self) -> None:
        data = valid_question_data()
        data["course_basis"] = [{"source": "第999页", "reason": "虚构来源"}]
        with self.assertRaisesRegex(ValueError, "未提供的来源"):
            validate_output(data, "question_optimize", ["第270页"])

    def test_rejects_wrong_question_counts(self) -> None:
        data = valid_question_data()
        data["optimized_questions"] = data["optimized_questions"][:2]
        with self.assertRaisesRegex(ValueError, "恰好包含 3 项"):
            validate_output(data, "question_optimize", ["第270页"])

    def test_rejects_evaluation_level_that_does_not_match_score(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["score"] = 91
        with self.assertRaisesRegex(ValueError, "必须与分数对应为“深度型”"):
            validate_output(data, "question_optimize", ["第270页"])

    def test_accepts_all_question_evaluation_boundaries(self) -> None:
        for score, level in [(60, "简单"), (75, "简单"), (76, "思考型"), (90, "思考型"), (91, "深度型"), (100, "深度型")]:
            with self.subTest(score=score):
                data = valid_question_data()
                data["question_evaluation"]["score"] = score
                data["question_evaluation"]["level"] = level
                validate_output(data, "question_optimize", ["第270页"])

    def test_rejects_legacy_question_diagnosis(self) -> None:
        data = valid_question_data()
        data["question_diagnosis"] = "旧字段不应再出现。"
        with self.assertRaisesRegex(ValueError, "不允许的字段.*question_diagnosis"):
            validate_output(data, "question_optimize", ["第270页"])


if __name__ == "__main__":
    unittest.main()
