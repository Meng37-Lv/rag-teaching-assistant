from __future__ import annotations

import json
import re
import sys
from time import perf_counter
from dataclasses import dataclass
from typing import Any

from src.config import Settings
from src.llm_client import LLMClient, LLMCompletion
from src.prompts import (
    build_answer_messages,
    build_json_repair_messages,
    build_question_messages,
    build_truncation_retry_messages,
)
from src.retriever import CourseRetriever, RetrievedChunk, format_context


class ModelOutputError(ValueError):
    def __init__(
        self,
        message: str,
        raw_output: str,
        finish_reason: str | None = None,
        completion_tokens: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.finish_reason = finish_reason
        self.completion_tokens = completion_tokens
        self.max_tokens = max_tokens


@dataclass(frozen=True)
class RAGResult:
    task_type: str
    retrieved_chunks: list[RetrievedChunk]
    raw_output: str
    data: dict[str, Any]
    repaired: bool
    retrieval_seconds: float
    llm_seconds: float
    total_seconds: float
    retried_original_task: bool
    first_finish_reason: str
    final_finish_reason: str
    first_completion_tokens: int | None
    final_completion_tokens: int | None
    first_max_tokens: int
    final_max_tokens: int


def parse_json_output(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as first_error:
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if not match:
            raise ModelOutputError(f"JSON 解析失败：{first_error}", raw_output) from first_error
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as second_error:
            raise ModelOutputError(f"JSON 代码块解析失败：{second_error}", raw_output) from second_error
    if not isinstance(value, dict):
        raise ModelOutputError("模型输出的 JSON 顶层必须是对象。", raw_output)
    return value


def _require_fields(data: dict[str, Any], fields: list[str]) -> None:
    missing = [name for name in fields if name not in data]
    if missing:
        raise ValueError(f"缺少必要字段：{', '.join(missing)}")


def _require_string(data: dict[str, Any], name: str) -> None:
    if not isinstance(data.get(name), str):
        raise ValueError(f"字段 {name} 必须是字符串。")


def _validate_course_basis(data: dict[str, Any], allowed_sources: set[str]) -> None:
    basis = data.get("course_basis")
    if not isinstance(basis, list):
        raise ValueError("course_basis 必须是数组。")
    for item in basis:
        if not isinstance(item, dict):
            raise ValueError("course_basis 每一项必须是对象。")
        if not isinstance(item.get("source"), str) or not isinstance(item.get("reason"), str):
            raise ValueError("course_basis 的 source 和 reason 必须是字符串。")
        if item["source"] not in allowed_sources:
            raise ValueError(f"course_basis 使用了未提供的来源：{item['source']}")


def validate_output(
    data: dict[str, Any],
    task_type: str,
    sources: list[str],
    compact_retry: bool = False,
) -> None:
    if data.get("task_type") != task_type:
        raise ValueError(f"task_type 必须是 {task_type}。")
    course_basis = data.get("course_basis")
    if isinstance(course_basis, list) and len(course_basis) > 2:
        data["course_basis"] = course_basis[:2]
    allowed_sources = set(sources)

    if task_type == "question_optimize":
        fields = [
            "task_type",
            "original_question",
            "question_diagnosis",
            "optimized_questions",
            "deep_questions",
            "course_basis",
            "insufficiency_notice",
        ]
        _require_fields(data, fields)
        for name in ["original_question", "question_diagnosis", "insufficiency_notice"]:
            _require_string(data, name)
        diagnosis_sentences = [
            sentence for sentence in re.split(r"[。！？!?]+", data["question_diagnosis"]) if sentence.strip()
        ]
        if len(diagnosis_sentences) > 2:
            raise ValueError("question_diagnosis 最多包含 2 句话。")
        if len(data["question_diagnosis"]) > 120:
            raise ValueError("question_diagnosis 不得超过 120 字。")
        optimized = data["optimized_questions"]
        deep = data["deep_questions"]
        if not isinstance(optimized, list) or len(optimized) != 3:
            raise ValueError("optimized_questions 必须恰好包含 3 项。")
        if not isinstance(deep, list) or len(deep) != 2:
            raise ValueError("deep_questions 必须恰好包含 2 项。")
        for item in optimized:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(name), str) for name in ["question", "improvement_focus"]
            ):
                raise ValueError("optimized_questions 每项必须含字符串 question 和 improvement_focus。")
            if len(item["question"]) > 100 or len(item["improvement_focus"]) > 40:
                raise ValueError("优化问题不得超过100字，improvement_focus不得超过40字。")
        for item in deep:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(name), str) for name in ["question", "thinking_dimension"]
            ):
                raise ValueError("deep_questions 每项必须含字符串 question 和 thinking_dimension。")
            if len(item["question"]) > 100 or len(item["thinking_dimension"]) > 40:
                raise ValueError("深度问题不得超过100字，thinking_dimension不得超过40字。")
    elif task_type == "answer_evaluate":
        fields = [
            "task_type",
            "question",
            "student_answer",
            "overall_evaluation",
            "strengths",
            "issues",
            "improvement_suggestions",
            "improved_answer",
            "course_basis",
            "insufficiency_notice",
        ]
        _require_fields(data, fields)
        for name in [
            "question",
            "student_answer",
            "overall_evaluation",
            "improved_answer",
            "insufficiency_notice",
        ]:
            _require_string(data, name)
        strengths = data["strengths"]
        issues = data["issues"]
        suggestions = data["improvement_suggestions"]
        if not isinstance(strengths, list) or not strengths or not all(isinstance(x, str) for x in strengths):
            raise ValueError("strengths 必须是至少包含 1 条字符串的数组。")
        if len(strengths) > 3:
            raise ValueError("strengths 最多包含 3 项。")
        if not isinstance(suggestions, list) or not all(isinstance(x, str) for x in suggestions):
            raise ValueError("improvement_suggestions 必须是字符串数组。")
        if len(suggestions) > 3:
            raise ValueError("improvement_suggestions 最多包含 3 项。")
        if not isinstance(issues, list):
            raise ValueError("issues 必须是数组。")
        if len(issues) > 3:
            raise ValueError("issues 最多包含 3 项。")
        if len(data["improved_answer"]) > 200:
            raise ValueError("improved_answer 必须控制在 200 个字符以内。")
        for item in issues:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(name), str)
                for name in ["type", "description", "evidence_or_reason"]
            ):
                raise ValueError("issues 每项必须包含 type、description、evidence_or_reason 字符串。")
    else:
        raise ValueError(f"不支持的任务类型：{task_type}")

    _validate_course_basis(data, allowed_sources)
    if task_type == "question_optimize":
        if len(data["course_basis"]) > 2:
            raise ValueError("question_optimize 的 course_basis 最多包含 2 项。")
        if any(len(item["reason"]) > 60 for item in data["course_basis"]):
            raise ValueError("question_optimize 的 course_basis.reason 不得超过 60 字。")
    elif compact_retry:
        if len(data["course_basis"]) > 2:
            raise ValueError("截断重试时 course_basis 最多包含 2 项。")
        if any(len(item["reason"]) > 30 for item in data["course_basis"]):
            raise ValueError("截断重试时 course_basis.reason 不得超过 30 字。")


def is_unterminated_json(error: Exception) -> bool:
    return "Unterminated string" in str(error)


class RAGService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.retriever = CourseRetriever()
        self.llm = LLMClient(settings)

    def _generate(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        chunks: list[RetrievedChunk],
        max_tokens: int,
        retry_max_tokens: int,
        started_at: float,
        retrieval_seconds: float,
    ) -> RAGResult:
        sources = list(dict.fromkeys(chunk.source for chunk in chunks))
        llm_started_at = perf_counter()
        try:
            first_response = self.llm.complete(messages, max_tokens=max_tokens)
        except Exception:
            failed_at = perf_counter()
            print(f"检索耗时：{retrieval_seconds:.3f} 秒", file=sys.stderr)
            print(f"LLM耗时：{failed_at - llm_started_at:.3f} 秒", file=sys.stderr)
            print(f"总耗时：{failed_at - started_at:.3f} 秒", file=sys.stderr)
            raise
        response = first_response
        retried_original_task = False
        repaired = False

        try:
            if response.finish_reason == "length":
                raise ModelOutputError(
                    "模型输出因达到max_tokens被截断。",
                    response.content,
                    response.finish_reason,
                    response.completion_tokens,
                    response.max_tokens,
                )
            data = parse_json_output(response.content)
            validate_output(data, task_type, sources)
        except (ModelOutputError, ValueError) as first_error:
            truncated = response.finish_reason == "length" or is_unterminated_json(first_error)
            if truncated:
                retried_original_task = True
                retry_messages = build_truncation_retry_messages(messages, task_type)
                try:
                    response = self.llm.complete(retry_messages, max_tokens=retry_max_tokens)
                except Exception:
                    failed_at = perf_counter()
                    print(f"检索耗时：{retrieval_seconds:.3f} 秒", file=sys.stderr)
                    print(f"LLM耗时：{failed_at - llm_started_at:.3f} 秒", file=sys.stderr)
                    print(f"总耗时：{failed_at - started_at:.3f} 秒", file=sys.stderr)
                    raise
                if response.finish_reason == "length":
                    raise ModelOutputError(
                        f"原始任务重试后仍被截断，finish_reason={response.finish_reason}。",
                        response.content,
                        response.finish_reason,
                        response.completion_tokens,
                        response.max_tokens,
                    )
                try:
                    data = parse_json_output(response.content)
                    validate_output(data, task_type, sources, compact_retry=True)
                except (ModelOutputError, ValueError) as retry_error:
                    if is_unterminated_json(retry_error):
                        raise ModelOutputError(
                            f"原始任务重试后JSON仍被截断，finish_reason={response.finish_reason}。",
                            response.content,
                            response.finish_reason,
                            response.completion_tokens,
                            response.max_tokens,
                        ) from retry_error
                    first_error = retry_error
                else:
                    first_error = None

            if first_error is not None and not isinstance(first_error, ModelOutputError):
                raise ModelOutputError(
                    f"模型输出JSON结构校验不通过，不执行格式修复：{first_error}",
                    response.content,
                    response.finish_reason,
                    response.completion_tokens,
                    response.max_tokens,
                ) from first_error

            if first_error is not None and response.finish_reason != "length":
                repair_messages = build_json_repair_messages(
                    response.content,
                    task_type,
                    str(first_error),
                    sources,
                )
                try:
                    response = self.llm.complete(repair_messages, max_tokens=response.max_tokens)
                except Exception:
                    failed_at = perf_counter()
                    print(f"检索耗时：{retrieval_seconds:.3f} 秒", file=sys.stderr)
                    print(f"LLM耗时：{failed_at - llm_started_at:.3f} 秒", file=sys.stderr)
                    print(f"总耗时：{failed_at - started_at:.3f} 秒", file=sys.stderr)
                    raise
                repaired = True
                if response.finish_reason == "length":
                    raise ModelOutputError(
                        f"JSON格式修复响应被截断，finish_reason={response.finish_reason}。",
                        response.content,
                        response.finish_reason,
                        response.completion_tokens,
                        response.max_tokens,
                    )
            try:
                if repaired:
                    data = parse_json_output(response.content)
                    validate_output(data, task_type, sources, compact_retry=retried_original_task)
            except (ModelOutputError, ValueError) as second_error:
                raise ModelOutputError(
                    f"模型输出处理后仍不合规，finish_reason={response.finish_reason}：{second_error}",
                    response.content,
                    response.finish_reason,
                    response.completion_tokens,
                    response.max_tokens,
                ) from second_error

        completed_at = perf_counter()
        return RAGResult(
            task_type,
            chunks,
            response.content,
            data,
            repaired,
            retrieval_seconds,
            completed_at - llm_started_at,
            completed_at - started_at,
            retried_original_task,
            first_response.finish_reason,
            response.finish_reason,
            first_response.completion_tokens,
            response.completion_tokens,
            first_response.max_tokens,
            response.max_tokens,
        )

    def question_optimize(self, question: str, top_k: int) -> RAGResult:
        started_at = perf_counter()
        question = question.strip()
        if not question:
            raise ValueError("学生问题不能为空。")
        retrieval_started_at = perf_counter()
        chunks = self.retriever.retrieve(question, top_k)[:3]
        retrieval_seconds = perf_counter() - retrieval_started_at
        context = format_context(
            chunks,
            self.settings.max_context_chars,
            self.settings.max_chunk_chars,
        )
        sources = list(dict.fromkeys(chunk.source for chunk in chunks))
        messages = build_question_messages(question, context, sources)
        return self._generate(
            "question_optimize",
            messages,
            chunks,
            max_tokens=900,
            retry_max_tokens=1100,
            started_at=started_at,
            retrieval_seconds=retrieval_seconds,
        )

    def answer_evaluate(self, question: str, student_answer: str, top_k: int) -> RAGResult:
        started_at = perf_counter()
        question = question.strip()
        student_answer = student_answer.strip()
        if not question:
            raise ValueError("问题不能为空。")
        if not student_answer:
            raise ValueError("学生回答不能为空。")
        retrieval_query = f"{question}\n学生回答：{student_answer}"
        retrieval_started_at = perf_counter()
        chunks = self.retriever.retrieve(retrieval_query, top_k)[:3]
        retrieval_seconds = perf_counter() - retrieval_started_at
        context = format_context(
            chunks,
            self.settings.max_context_chars,
            self.settings.max_chunk_chars,
        )
        sources = list(dict.fromkeys(chunk.source for chunk in chunks))
        messages = build_answer_messages(question, student_answer, context, sources)
        return self._generate(
            "answer_evaluate",
            messages,
            chunks,
            max_tokens=900,
            retry_max_tokens=1100,
            started_at=started_at,
            retrieval_seconds=retrieval_seconds,
        )
