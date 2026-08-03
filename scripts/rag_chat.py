from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError  # noqa: E402

from src.config import ConfigError, load_settings  # noqa: E402
from src.rag_service import ModelOutputError, RAGResult, RAGService  # noqa: E402
from src.retriever import relevance_label  # noqa: E402
from src.source_mapper import OriginalSourceRetriever, SourcePageMapper  # noqa: E402


def print_retrieval(result: RAGResult, source_mapper: SourcePageMapper) -> None:
    print("\n1. 检索到的课程资料来源与摘要")
    for rank, chunk in enumerate(result.retrieved_chunks, start=1):
        preview = source_mapper.sanitize_text(" ".join(chunk.text.split())[:180])
        print(f"[{rank}] {chunk.source}（相关度：{relevance_label(chunk.score)}）")
        print(f"    {preview}")


def print_readable(data: dict[str, Any]) -> None:
    print("\n3. 格式化后的易读结果")
    if data["task_type"] == "question_optimize":
        print(f"原问题诊断：{data['question_diagnosis']}")
        print("优化问题：")
        for index, item in enumerate(data["optimized_questions"], start=1):
            print(f"  {index}. {item['question']}")
            print(f"     改进方向：{item['improvement_focus']}")
        print("深度思考问题：")
        for index, item in enumerate(data["deep_questions"], start=1):
            print(f"  {index}. {item['question']}")
            print(f"     思考维度：{item['thinking_dimension']}")
    else:
        print(f"总体评价：{data['overall_evaluation']}")
        print("值得肯定：")
        for item in data["strengths"]:
            print(f"  - {item}")
        print("需要改进：")
        if not data["issues"]:
            print("  - 暂未发现需要强行指出的问题。")
        for item in data["issues"]:
            print(f"  - [{item['type']}] {item['description']}")
            print(f"    依据：{item['evidence_or_reason']}")
        print("改进建议：")
        for item in data["improvement_suggestions"]:
            print(f"  - {item}")
        print(f"优化答案：{data['improved_answer']}")

    if data["course_basis"]:
        print("课程依据：")
        for item in data["course_basis"]:
            print(f"  - {item['source']}：{item['reason']}")
    if data["insufficiency_notice"]:
        print(f"资料不足提示：{data['insufficiency_notice']}")


def print_result(result: RAGResult, source_mapper: SourcePageMapper) -> None:
    data = source_mapper.sanitize_value(result.data)
    print_retrieval(result, source_mapper)
    print("\n2. LLM 生成的结构化结果")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if result.repaired:
        print("提示：模型首次输出不合规，程序已完成一次 JSON 格式修复。")
    print(f"首次finish_reason：{result.first_finish_reason}")
    print(f"首次completion tokens：{result.first_completion_tokens}/{result.first_max_tokens}")
    print(f"是否触发原始任务重试：{'是' if result.retried_original_task else '否'}")
    if result.retried_original_task or result.repaired:
        print(f"最终finish_reason：{result.final_finish_reason}")
        print(f"最终completion tokens：{result.final_completion_tokens}/{result.final_max_tokens}")
    print_readable(data)
    print("\n性能统计")
    print(f"检索耗时：{result.retrieval_seconds:.3f} 秒")
    print(f"LLM耗时：{result.llm_seconds:.3f} 秒")
    print(f"总耗时：{result.total_seconds:.3f} 秒")


def run_once(
    service: RAGService,
    mode: str,
    question: str,
    answer: str | None,
    top_k: int,
    source_mapper: SourcePageMapper,
) -> None:
    started_at = perf_counter()
    try:
        if mode == "question_optimize":
            result = service.question_optimize(question, top_k)
        else:
            if answer is None:
                raise ValueError("answer_evaluate 模式必须提供学生回答。")
            result = service.answer_evaluate(question, answer, top_k)
    except Exception:
        print(f"本次请求失败，总耗时：{perf_counter() - started_at:.3f} 秒", file=sys.stderr)
        raise
    print_result(result, source_mapper)


def interactive(service: RAGService, top_k: int, source_mapper: SourcePageMapper) -> None:
    while True:
        print("\n请选择功能：")
        print("1. 优化学生问题")
        print("2. 评价学生答案")
        print("0. 退出")
        choice = input("请输入选项：").strip()
        if choice == "0":
            print("已退出。")
            return
        if choice == "1":
            run_once(service, "question_optimize", input("请输入学生问题：").strip(), None, top_k, source_mapper)
        elif choice == "2":
            question = input("请输入问题：").strip()
            answer = input("请输入学生回答：").strip()
            run_once(service, "answer_evaluate", question, answer, top_k, source_mapper)
        else:
            print("无效选项，请输入 0、1 或 2。")


def build_parser(default_top_k: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基于课程知识库的教学辅助命令行程序。")
    parser.add_argument("--mode", choices=["question_optimize", "answer_evaluate"])
    parser.add_argument("--question", help="学生问题。")
    parser.add_argument("--answer", help="学生回答，仅 answer_evaluate 模式需要。")
    parser.add_argument("--top-k", type=int, default=default_top_k, help="检索课程片段数量。")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        settings = load_settings()
        args = build_parser(settings.default_top_k).parse_args()
        if args.top_k <= 0:
            raise ValueError("--top-k 必须大于 0。")
        service = RAGService(settings)
        source_mapper = SourcePageMapper.from_ppt_directory(PROJECT_ROOT / "ppt")
        service.retriever = OriginalSourceRetriever(service.retriever, source_mapper)
        if args.mode:
            if not args.question:
                raise ValueError("命令行模式必须提供 --question。")
            run_once(service, args.mode, args.question, args.answer, args.top_k, source_mapper)
        else:
            interactive(service, args.top_k, source_mapper)
        return 0
    except (ConfigError, ValueError, FileNotFoundError) as error:
        print(f"运行失败：{error}", file=sys.stderr)
        if isinstance(error, ModelOutputError):
            print(f"finish_reason：{error.finish_reason or '未知'}", file=sys.stderr)
            print(f"completion tokens：{error.completion_tokens}/{error.max_tokens}", file=sys.stderr)
            print(f"模型输出长度：{len(error.raw_output)}字符（为避免泄露和刷屏，不打印完整内容）", file=sys.stderr)
        return 2
    except APITimeoutError:
        print("LLM 请求在唯一一次重试后仍超时，请检查网络、模型响应速度或适当增大 LLM_TIMEOUT_SECONDS。", file=sys.stderr)
        return 1
    except RateLimitError:
        print("LLM API 在唯一一次重试后仍返回 HTTP 429，请稍后再试并检查账户配额。", file=sys.stderr)
        return 1
    except APIConnectionError:
        print("唯一一次重试后仍无法连接 LLM API，请检查网络、代理和 LLM_BASE_URL。", file=sys.stderr)
        return 1
    except APIStatusError as error:
        print(f"LLM API 返回错误，HTTP 状态码：{error.status_code}", file=sys.stderr)
        print(str(error)[:800], file=sys.stderr)
        return 1
    except Exception as error:
        print(f"未预期的运行错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
