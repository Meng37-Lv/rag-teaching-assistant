from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.web_api import PresentationQuestionsResponse, QuestionEvaluation


class ApiContractTests(unittest.TestCase):
    def test_question_evaluation_pydantic_contract(self) -> None:
        evaluation = QuestionEvaluation.model_validate(
            {
                "score": 84,
                "raw_score": 84,
                "floor_applied": False,
                "level": "思考型",
                "evaluation": "需要解释机制和条件。",
                "suggestion": "可加入比较与应用边界。",
                "score_interpretation": "75分表示基本达标且有改进空间；不代表按批次强制调分。",
                "evidence_status": "insufficient",
                "score_breakdown": [
                    {"key": "material_relevance", "label": "材料关联", "max_score": 25, "anchor": "锚点", "score": 20, "reason": "理由", "evidence": []},
                    {"key": "thinking_value", "label": "思考价值", "max_score": 35, "anchor": "锚点", "score": 30, "reason": "理由", "evidence": []},
                    {"key": "clarity", "label": "表达清晰", "max_score": 15, "anchor": "锚点", "score": 12, "reason": "理由", "evidence": []},
                    {"key": "discussability", "label": "可讨论性", "max_score": 25, "anchor": "锚点", "score": 22, "reason": "理由", "evidence": []},
                ],
            }
        )
        self.assertEqual(evaluation.level, "思考型")

    def test_question_evaluation_rejects_mismatched_level(self) -> None:
        with self.assertRaises(ValidationError):
            QuestionEvaluation.model_validate(
                {
                    "score": 94,
                    "level": "简单",
                    "evaluation": "评价",
                    "suggestion": "建议",
                }
            )

    def test_presentation_response_requires_three_ordered_questions_per_level(self) -> None:
        questions = [
            {
                "level": level,
                "label": label,
                "score": score,
                "question": f"{label}问题{index}",
            }
            for level, label, score in (
                ("easy", "简单", 60),
                ("medium", "中等", 80),
                ("hard", "困难", 100),
            )
            for index in range(1, 4)
        ]
        response = PresentationQuestionsResponse.model_validate({"questions": questions})
        self.assertEqual(len(response.questions), 9)


if __name__ == "__main__":
    unittest.main()
