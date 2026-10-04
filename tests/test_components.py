from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.rag_service import parse_json_output, validate_output
from src.retriever import RetrievedChunk


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
            "score_interpretation": "75分表示基本达标且有改进空间；不代表按批次强制调分。",
            "evidence_status": "insufficient",
            "score_breakdown": [
                {"key": "material_relevance", "score": 17, "reason": "部分关联课程材料。", "evidence": []},
                {"key": "thinking_value", "score": 25, "reason": "有进一步解释空间。", "evidence": []},
                {"key": "clarity", "score": 12, "reason": "问题含义基本清楚。", "evidence": []},
                {"key": "discussability", "score": 14, "reason": "可加入比较讨论。", "evidence": []},
            ],
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
        "insufficiency_notice": "当前检索片段不足以逐项提供材料证据。",
    }


def valid_answer_data() -> dict[str, object]:
    return {
        "task_type": "answer_evaluate",
        "question": "深度学习如何学习特征？",
        "student_answer": "深度学习通过多层表示学习特征。",
        "score": 75,
        "level": "简单",
        "score_interpretation": "75分表示基本达标且有改进空间；不代表按批次强制调分。",
        "evidence_status": "sufficient",
        "score_breakdown": [
            {"key": "material_alignment", "score": 23, "reason": "回答使用了当前材料。", "evidence": [{"source": "第270页", "quote": "深度学习通过多层表示学习特征"}]},
            {"key": "correctness", "score": 30, "reason": "核心表述正确。", "evidence": [{"source": "第270页", "quote": "深度学习通过多层表示学习特征"}]},
            {"key": "completeness", "score": 15, "reason": "覆盖主要机制但仍可补充。", "evidence": [{"source": "第270页", "quote": "深度学习通过多层表示学习特征"}]},
            {"key": "expression", "score": 7, "reason": "表达清楚。", "evidence": [{"source": "第270页", "quote": "深度学习通过多层表示学习特征"}]},
        ],
        "overall_evaluation": "基本回答了问题。",
        "strengths": ["抓住了多层表示学习。"],
        "issues": [],
        "improvement_suggestions": ["补充特征逐层抽象的过程。"],
        "improved_answer": "深度学习通过多层神经网络逐层学习和抽象特征。",
        "course_basis": [{"source": "第270页", "reason": "支持特征学习表述"}],
        "insufficiency_notice": "",
    }


class ComponentTests(unittest.TestCase):
    def test_floor_boundaries_preserve_components_and_make_one_llm_call(self):
        from types import SimpleNamespace
        from time import perf_counter
        from src.rag_service import RAGService
        from src.llm_client import LLMCompletion
        from unittest.mock import Mock
        for total in (0, 59, 60, 61, 100):
            for task in ("question_optimize", "answer_evaluate"):
                data = valid_question_data() if task == "question_optimize" else valid_answer_data()
                block = data["question_evaluation"] if task == "question_optimize" else data
                block["evidence_status"] = "insufficient"
                data["course_basis"] = []
                data["insufficiency_notice"] = "材料不足，评价可靠性不足。"
                remaining = total
                limits = (25, 35, 15, 25) if task == "question_optimize" else (30, 40, 20, 10)
                original = []
                for item, limit in zip(block["score_breakdown"], limits):
                    item["score"] = min(limit, remaining)
                    remaining -= item["score"]
                    item["evidence"] = []
                    original.append(item["score"])
                service = RAGService.__new__(RAGService)
                service.llm = Mock()
                service.llm.complete.return_value = LLMCompletion(json.dumps(data, ensure_ascii=False), "stop", 100, 900)
                result = service._generate(task, [], [], 900, 1100, perf_counter(), 0, "测试")
                actual = result.data["question_evaluation"] if task == "question_optimize" else result.data
                self.assertEqual(actual["raw_score"], total)
                self.assertEqual(actual["score"], max(60, total))
                self.assertEqual(actual["floor_applied"], total < 60)
                self.assertEqual([item["score"] for item in actual["score_breakdown"]], original)
                service.llm.complete.assert_called_once()

    def test_insufficient_scores_excluded_but_activity_retained(self):
        from types import SimpleNamespace
        from src.teaching_analytics import calculate_statistics
        events = [SimpleNamespace(task_type="question_optimize", score=60, level="简单", course_basis_json=[], output_json={"question_evaluation": {"evidence_status": "insufficient", "floor_applied": True}}),
                  SimpleNamespace(task_type="answer_evaluate", score=75, level="简单", course_basis_json=[], output_json={})]
        stats = calculate_statistics(events)
        self.assertEqual(stats["score_distribution"]["scores"], [75])
        self.assertEqual(stats["sample_size"], 2)
        self.assertEqual(sum(stats["usage_counts"].values()), 2)

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
        data["question_evaluation"]["score_breakdown"] = [
            {"key": "material_relevance", "score": 23, "reason": "理由", "evidence": []},
            {"key": "thinking_value", "score": 35, "reason": "理由", "evidence": []},
            {"key": "clarity", "score": 15, "reason": "理由", "evidence": []},
            {"key": "discussability", "score": 18, "reason": "理由", "evidence": []},
        ]
        validate_output(data, "question_optimize", ["第270页"])
        self.assertEqual(data["question_evaluation"]["level"], "深度型")

    def test_accepts_all_question_evaluation_boundaries(self) -> None:
        cases = [
            (60, "简单", [15, 20, 10, 15]),
            (75, "简单", [18, 25, 12, 20]),
            (76, "思考型", [19, 25, 12, 20]),
            (90, "思考型", [22, 32, 14, 22]),
            (91, "深度型", [23, 33, 14, 21]),
            (100, "深度型", [25, 35, 15, 25]),
        ]
        for score, level, component_scores in cases:
            with self.subTest(score=score):
                data = valid_question_data()
                data["question_evaluation"]["score"] = score
                data["question_evaluation"]["level"] = level
                for item, component_score in zip(data["question_evaluation"]["score_breakdown"], component_scores):
                    item["score"] = component_score
                validate_output(data, "question_optimize", ["第270页"])

    def test_rejects_score_that_does_not_equal_breakdown_sum(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["score"] = 69
        validate_output(data, "question_optimize", ["第270页"])
        self.assertEqual(data["question_evaluation"]["score"], 68)

    def test_floor_below_60_keeps_raw_score(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["score"] = 59
        data["question_evaluation"]["score_breakdown"] = [
            {"key": "material_relevance", "score": 15, "reason": "理由", "evidence": []},
            {"key": "thinking_value", "score": 20, "reason": "理由", "evidence": []},
            {"key": "clarity", "score": 10, "reason": "理由", "evidence": []},
            {"key": "discussability", "score": 14, "reason": "理由", "evidence": []},
        ]
        validate_output(data, "question_optimize", ["第270页"])
        self.assertEqual(data["question_evaluation"]["raw_score"], 59)
        self.assertEqual(data["question_evaluation"]["score"], 60)

    def test_accepts_breakdown_boundaries_and_computes_sum(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["score_breakdown"] = [
            {"key": "material_relevance", "score": 25, "reason": "满分锚点。", "evidence": []},
            {"key": "thinking_value", "score": 35, "reason": "满分锚点。", "evidence": []},
            {"key": "clarity", "score": 0, "reason": "最低边界。", "evidence": []},
            {"key": "discussability", "score": 0, "reason": "最低边界。", "evidence": []},
        ]
        data["question_evaluation"]["score"] = 60
        data["question_evaluation"]["level"] = "简单"
        validate_output(data, "question_optimize", ["第270页"])

    def test_validates_real_and_relevant_material_evidence(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["evidence_status"] = "sufficient"
        data["insufficiency_notice"] = ""
        evidence = [{"source": "第270页", "quote": "深度学习通过多层表示学习特征"}]
        for item in data["question_evaluation"]["score_breakdown"]:
            item["evidence"] = evidence
        chunk = RetrievedChunk(1, "深度学习通过多层表示学习特征，并用于课程案例。", 270, 0.9, "第270页")
        validate_output(data, "question_optimize", ["第270页"], retrieved_chunks=[chunk], related_text="深度学习如何学习特征？")

    def test_rejects_fake_or_unrelated_material_evidence(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["evidence_status"] = "sufficient"
        data["insufficiency_notice"] = ""
        for item in data["question_evaluation"]["score_breakdown"]:
            item["evidence"] = [{"source": "第270页", "quote": "不存在的课程片段"}]
        chunk = RetrievedChunk(1, "深度学习通过多层表示学习特征。", 270, 0.9, "第270页")
        with self.assertRaisesRegex(ValueError, "不在当前课程检索结果"):
            validate_output(data, "question_optimize", ["第270页"], retrieved_chunks=[chunk], related_text="深度学习如何学习特征？")

    def test_rejects_true_but_unrelated_material_evidence(self) -> None:
        data = valid_question_data()
        data["question_evaluation"]["evidence_status"] = "sufficient"
        data["insufficiency_notice"] = ""
        unrelated = [{"source": "第270页", "quote": "课程模型在行业中部署成本较高"}]
        for item in data["question_evaluation"]["score_breakdown"]:
            item["evidence"] = unrelated
        chunk = RetrievedChunk(1, "课程模型在行业中部署成本较高。", 270, 0.4, "第270页")
        with self.assertRaisesRegex(ValueError, "关联不足"):
            validate_output(data, "question_optimize", ["第270页"], retrieved_chunks=[chunk], related_text="深度学习如何学习特征？")

    def test_generation_structure_stays_three_optimized_and_two_deep_questions(self) -> None:
        data = valid_question_data()
        validate_output(data, "question_optimize", ["第270页"])
        self.assertEqual(len(data["optimized_questions"]), 3)
        self.assertEqual(len(data["deep_questions"]), 2)

    def test_validates_answer_breakdown_and_sum(self) -> None:
        data = valid_answer_data()
        chunk = RetrievedChunk(1, "深度学习通过多层表示学习特征，并用于课程案例。", 270, 0.9, "第270页")
        validate_output(data, "answer_evaluate", ["第270页"], retrieved_chunks=[chunk], related_text="深度学习如何学习特征？\n深度学习通过多层表示学习特征。")
        self.assertEqual(data["score"], sum(item["score"] for item in data["score_breakdown"]))

    def test_answer_evidence_shortage_is_explicit_without_forced_low_score(self) -> None:
        data = valid_answer_data()
        data["evidence_status"] = "insufficient"
        data["insufficiency_notice"] = "当前检索片段不足以核实答案中的部分内容。"
        for item in data["score_breakdown"]:
            item["evidence"] = []
        validate_output(data, "answer_evaluate", ["第270页"], retrieved_chunks=[], related_text="问题和答案")
        self.assertEqual(data["score"], 75)

    def test_rejects_legacy_question_diagnosis(self) -> None:
        data = valid_question_data()
        data["question_diagnosis"] = "旧字段不应再出现。"
        with self.assertRaisesRegex(ValueError, "不允许的字段.*question_diagnosis"):
            validate_output(data, "question_optimize", ["第270页"])


if __name__ == "__main__":
    unittest.main()
