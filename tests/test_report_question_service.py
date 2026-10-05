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


def grounded_output(material):
    data = _valid_output()
    data.update(status="ready", notice="")
    focus = "系统目标" if "系统目标" in material.extracted_text else "模型" if "模型" in material.extracted_text else material.segments[0].text[:2]
    questions = (
        f"为什么{focus}采用这一方案？", f"如何解释{focus}的适用条件？", f"如何比较{focus}与替代方案？",
        f"如何验证{focus}的可靠性？", f"{focus}可能受到什么偏差影响？", f"如何检验{focus}的因果关系？",
        f"如何评估{focus}的局限？", f"如何设计{focus}的改进验证？", f"应用{focus}需要权衡哪些约束？",
    )
    evidence = [{"file_id": seg.file_id, "filename": seg.filename, "segment_id": seg.segment_id, "location": seg.location, "quote": seg.text} for seg in material.segments]
    for index, item in enumerate(data["questions"]):
        intent = ("understanding", "argument", "application")[index // 3]
        marker = ("解释", "验证", "应用")[index // 3]
        item.update(question=questions[index], evidence=evidence,
                    basis_summary=f"材料围绕{focus}的相关内容进行说明",
                    relation_explanation=f"问题围绕{focus}，对{focus}进行{marker}。",
                    grounding={"material_focus": focus, "question_focus": focus, "intent": intent})
    return data


def comparison_example():
    material = parse_text_material("采用对照实验比较模型A与模型B。\n相同测试集上模型A准确率90%，模型B为70%。\n当前测试仅覆盖室内场景，尚未验证室外效果。", "对照实验汇报")
    data = grounded_output(material)
    questions = [
        "为什么用对照实验比较模型A与模型B？",
        "对照实验如何解释模型A与模型B的差异？",
        "对照实验的比较条件如何设置？",
        "相同测试集能否支持两个模型准确率的比较？",
        "如何验证模型A准确率90%的可靠性？",
        "模型B准确率70%可能受到哪些偏差影响？",
        "仅有室内测试时，如何评估室外应用的局限？",
        "如何设计从室内到室外的验证方案？",
        "将室内结果用于室外场景时，需要权衡哪些约束？",
    ]
    summaries = ["说明两个模型采用对照实验的比较方式", "比较相同测试集上两个模型的准确率结果", "说明室内场景与室外验证的关系"]
    focuses = ["对照实验", "准确率", "室内"]
    for index, item in enumerate(data["questions"]):
        focus = focuses[index // 3]
        intent = ("understanding", "argument", "application")[index // 3]
        item.update(question=questions[index], basis_summary=summaries[index // 3],
                    grounding={"material_focus": focus, "question_focus": focus, "intent": intent},
                    relation_explanation=f"问题围绕{focus}，对{focus}进行{('解释', '验证', '应用')[index // 3]}。")
    return material, data


class FakeLLMClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LLMCompletion:
        content = self.contents[self.calls]
        self.calls += 1
        return LLMCompletion(content, "stop", 100, max_tokens)


class ReportQuestionServiceTests(unittest.TestCase):
    def test_three_natural_difficulties_with_paraphrased_summaries(self):
        from src.report_question_service import public_presentation_result
        material, data = comparison_example()
        fake = FakeLLMClient([json.dumps(data, ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(material)
        self.assertEqual(fake.calls, 1)
        for item in result.data["questions"]:
            self.assertNotIn(item["basis_summary"], material.extracted_text)
            self.assertNotIn("针对“", item["question"])
        visible = public_presentation_result(result.data)
        self.assertNotIn("evidence", json.dumps(visible))
        self.assertNotIn("segment_id", json.dumps(visible))
        self.assertNotIn("grounding", json.dumps(visible))

    def test_unrelated_question_with_real_quote_and_shared_keywords_is_rejected(self):
        material, data = comparison_example()
        data["questions"][0]["question"] = "对照实验比较模型A与模型B，为什么火星适合移民？"
        with self.assertRaises(ValueError):
            validate_report_questions(data, material)

    def test_verbatim_overview_and_added_summary_facts_are_rejected(self):
        from copy import deepcopy
        material, data = comparison_example()
        copied = deepcopy(data)
        copied["questions"][0]["basis_summary"] = "采用对照实验比较模型A与模型B"
        with self.assertRaisesRegex(ValueError, "截取"):
            validate_report_questions(copied, material)
        fabricated = deepcopy(data)
        fabricated["questions"][0]["basis_summary"] = "实验比较模型A与模型B，模型A准确率99%"
        with self.assertRaisesRegex(ValueError, "数值"):
            validate_report_questions(fabricated, material)

    def test_model_validation_failure_is_not_material_insufficiency(self):
        from src.report_question_service import ReportQuestionOutputError
        material, data = comparison_example()
        data["questions"][0]["evidence"][0]["location"] = "第999页"
        fake = FakeLLMClient([json.dumps(data, ensure_ascii=False)] * 2)
        with self.assertRaises(ReportQuestionOutputError):
            ReportQuestionService(self.settings, fake).generate(material)
        self.assertEqual(fake.calls, 2)

    def test_natural_grounded_question_should_be_accepted(self):
        """Relevant natural questions no longer require literal quotations."""
        data = grounded_output(self.material)
        data["questions"][0]["question"] = "为什么将系统目标拆分为两个核心功能，而不是合并实现？"
        validate_report_questions(data, self.material)

    def test_short_informative_material_over_threshold_can_be_used(self):
        material = parse_text_material("模型A效果优于模型B", "简短实验结果")
        fake = FakeLLMClient([json.dumps(grounded_output(material), ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(material)
        self.assertEqual(result.data["status"], "ready")
        self.assertEqual(fake.calls, 1)

    def test_short_informative_lines_should_not_be_rejected_only_by_length(self):
        """Short evidence lines are preserved and may be used together."""
        material = parse_text_material("对照：A/B\n样本：100\nA：90%\nB：70%", "简短对照实验")
        fake = FakeLLMClient([json.dumps(grounded_output(material), ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(material)
        self.assertEqual(fake.calls, 1)
        self.assertNotEqual(result.data["status"], "insufficient")
        self.assertEqual([ref["location"] for ref in result.data["questions"][0]["evidence"]], ["第1行", "第2行", "第3行", "第4行"])

    def test_evidence_scope_quote_location_and_question(self):
        from copy import deepcopy
        valid = grounded_output(self.material)
        validate_report_questions(deepcopy(valid), self.material)
        for field, value in (("segment_id", "foreign"), ("quote", "材料不存在的事实说明"), ("location", "第999页"), ("file_id", "other-file")):
            invalid = deepcopy(valid)
            from copy import deepcopy
            invalid["questions"][0]["evidence"] = deepcopy(invalid["questions"][0]["evidence"])
            invalid["questions"][0]["evidence"][0][field] = value
            with self.assertRaises(ValueError):
                validate_report_questions(invalid, self.material)
        unrelated = deepcopy(valid)
        unrelated["questions"][0]["question"] = "材料介绍系统目标，为什么火星适合移民？"
        with self.assertRaises(ValueError):
            validate_report_questions(unrelated, self.material)

    def test_insufficient_material_does_not_force_questions(self):
        fake = FakeLLMClient([json.dumps({"status": "insufficient", "notice": "只有标题，缺少方法、结果与适用范围。", "questions": []}, ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(parse_text_material("标题"))
        self.assertEqual(result.data["status"], "insufficient")
        self.assertEqual(result.data["questions"], [])
        self.assertEqual(fake.calls, 1)
        output = {"status": "insufficient", "notice": "缺少方法和结果，无法支持九题", "questions": []}
        fake = FakeLLMClient([json.dumps(output, ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(self.material)
        self.assertEqual(result.data, output)

    def test_multifile_segments_are_not_renumbered(self):
        from src.web_api import _combine_presentation_materials
        one = parse_text_material("第一行文字说明\n第二行介绍系统目标和设计约束", "甲.txt")
        two = parse_text_material("另一个文件介绍结果和验证方法", "乙.md")
        combined = _combine_presentation_materials([one, two])
        self.assertEqual(combined.segments, one.segments + two.segments)
        self.assertNotEqual(one.segments[0].file_id, two.segments[0].file_id)
        self.assertEqual(one.segments[1].location, "第2行")
        data = grounded_output(combined)
        validate_report_questions(data, combined)
        refs = data["questions"][0]["evidence"]
        self.assertEqual({ref["filename"] for ref in refs}, {"甲.txt", "乙.md"})
        self.assertEqual(refs[1]["location"], "第2行")

    def test_api_current_uploads_only_preview_and_course_history_isolation(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.course_data import CourseStore, CourseCreate, get_course_store
        from src.teaching_history import TeachingHistoryStore, get_history_store
        from src.web_api import app
        from src.llm_client import LLMCompletion
        class MockLLM:
            def complete(inner, messages, max_tokens):
                payload = json.loads(messages[1]["content"].split("<material>\n")[1].split("\n</material>")[0])
                from src.material_parser import ParsedMaterial, MaterialSegment
                material = ParsedMaterial("mock", "组合材料", "\n".join(seg["text"] for seg in payload["片段"]), tuple(MaterialSegment(**seg) for seg in payload["片段"]))
                if material.extracted_text == "标题":
                    output = {"status": "insufficient", "notice": "仅有标题，缺少方法与实验结果。", "questions": []}
                else:
                    output = grounded_output(material)
                return LLMCompletion(json.dumps(output, ensure_ascii=False), "stop", 100, max_tokens)
        with tempfile.TemporaryDirectory() as directory:
            store = CourseStore(Path(directory) / "courses.db")
            history = TeachingHistoryStore(store.db_path)
            one = store.create(CourseCreate(name="课程甲"))
            two = store.create(CourseCreate(name="课程乙"))
            app.dependency_overrides[get_course_store] = lambda: store
            app.dependency_overrides[get_history_store] = lambda: history
            runtime = SimpleNamespace(service=ReportQuestionService(self.settings, MockLLM()))
            try:
                client = TestClient(app)
                from tests.auth_helpers import login_test_client
                login_test_client(client, store)
                with patch("src.web_api._get_presentation_runtime", return_value=runtime), patch("src.web_api.course_directory", side_effect=AssertionError("不能回退课程extracted")):
                    preview = client.post("/api/presentation-preview", data={"course_id": one.id}, files=[("files", ("甲.txt", "本次文件解释模型方案和验证方法。".encode())), ("files", ("乙.md", "第二份材料说明数据指标和结果分析。".encode()))])
                    self.assertEqual(preview.status_code, 200)
                    self.assertEqual(len(preview.json()["materials"]), 2)
                    self.assertEqual(history.list(one.id)[1], 0)
                    result = client.post("/api/presentation-questions", data={"course_id": one.id, "text": "本次文本解释模型方案和验证方法。"})
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(len(result.json()["questions"]), 9)
                    self.assertEqual(history.list(one.id)[1], 1)
                    self.assertEqual(history.list(two.id)[1], 0)
                    csv = client.get(f"/api/courses/{one.id}/history/export.csv").text
                    self.assertIn("针对的内容", csv)
                    self.assertNotIn("segment_id", csv)
                    raw_event = history.list(one.id)[0][0]
                    file_id = raw_event.output_json["questions"][0]["evidence"][0]["file_id"]
                    self.assertNotIn(file_id, csv)
                    self.assertNotIn("evidence", result.json()["questions"][0])
                    self.assertNotIn("grounding", result.json()["questions"][0])
                    detail = client.get(f"/api/courses/{one.id}/history/{raw_event.id}").json()
                    self.assertNotIn("evidence", detail["output_json"]["questions"][0])
                    self.assertNotIn(file_id, json.dumps(detail))
                    legacy = history.add(course_id=one.id, task_type="presentation_questions", input_data={}, output_data=_valid_output())
                    old = client.get(f"/api/courses/{one.id}/history/{legacy.id}")
                    self.assertEqual(old.status_code, 200)
                    self.assertNotIn("basis_summary", old.json()["output_json"]["questions"][0])
                    missing = client.post("/api/presentation-questions", data={"course_id": "missing", "text": "材料"})
                    self.assertEqual(missing.status_code, 404)
                    empty = client.post("/api/presentation-questions", data={"course_id": two.id})
                    self.assertEqual(empty.status_code, 400)
                    insufficient = client.post("/api/presentation-questions", data={"course_id": two.id, "text": "标题"})
                    self.assertEqual(insufficient.json()["status"], "insufficient")
            finally:
                app.dependency_overrides.clear()

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
        fake = FakeLLMClient([json.dumps(grounded_output(self.material), ensure_ascii=False)])
        result = ReportQuestionService(self.settings, fake).generate(self.material)

        self.assertFalse(result.retried)
        self.assertEqual(
            [item["score"] for item in result.data["questions"]],
            [60, 60, 60, 80, 80, 80, 100, 100, 100],
        )

    def test_invalid_output_retries_only_once(self) -> None:
        invalid = grounded_output(self.material)
        invalid["questions"][0]["score"] = 50
        fake = FakeLLMClient(
            [
                json.dumps(invalid, ensure_ascii=False),
                json.dumps(grounded_output(self.material), ensure_ascii=False),
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
