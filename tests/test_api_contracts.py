from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.web_api import PresentationQuestionsResponse, QuestionEvaluation


class ApiContractTests(unittest.TestCase):
    def test_question_evaluation_pydantic_contract(self) -> None:
        evaluation = QuestionEvaluation.model_validate(
            {
                "score": 84,
                "level": "思考型",
                "evaluation": "需要解释机制和条件。",
                "suggestion": "可加入比较与应用边界。",
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
