from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
TEST_MESSAGE = "请只回复：LLM API 连接成功。"


class ConfigError(ValueError):
    """表示本地 LLM 配置不完整或不合法。"""


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"缺少 {name}，请在 .env 中填写有效值。")
    return value


def load_config() -> dict[str, object]:
    load_dotenv(ENV_PATH)

    api_key = require_env("LLM_API_KEY")
    base_url = require_env("LLM_BASE_URL").rstrip("/")
    model = require_env("LLM_MODEL")
    reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "high").strip() or "high"
    enable_thinking = os.getenv("LLM_ENABLE_THINKING", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    timeout_text = os.getenv("LLM_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout = float(timeout_text)
    except ValueError as error:
        raise ConfigError("LLM_TIMEOUT_SECONDS 必须是有效数字。") from error
    if timeout <= 0:
        raise ConfigError("LLM_TIMEOUT_SECONDS 必须大于 0。")

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "enable_thinking": enable_thinking,
        "timeout": timeout,
    }


def sanitize_error(error: Exception, api_key: str) -> str:
    summary = str(error).replace(api_key, "***")
    return summary[:800]


def print_api_error(error: Exception, api_key: str) -> None:
    summary = sanitize_error(error, api_key)

    if isinstance(error, AuthenticationError):
        advice = "请检查 LLM_API_KEY 是否正确、有效且未过期。"
    elif isinstance(error, PermissionDeniedError):
        advice = "请检查 API Key 是否有权访问当前模型或接口。"
    elif isinstance(error, NotFoundError):
        advice = "请核对 LLM_BASE_URL、LLM_MODEL 以及服务商是否支持 Chat Completions。"
    elif isinstance(error, RateLimitError):
        advice = "请求受到限流或账户额度不足，请稍后重试并检查余额与配额。"
    elif isinstance(error, APITimeoutError):
        advice = "请求超时，请检查网络，或适当增大 LLM_TIMEOUT_SECONDS。"
    elif isinstance(error, APIConnectionError):
        advice = "无法连接 API，请检查网络、代理、DNS 和 LLM_BASE_URL。"
    elif isinstance(error, APIStatusError):
        advice = "服务端返回异常状态，请根据状态码和响应摘要检查配置。"
    else:
        advice = "请检查第三方服务的 Chat Completions 兼容格式和返回结构。"

    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        print(f"HTTP 状态码：{status_code}", file=sys.stderr)
    print(f"API 调用失败：{summary}", file=sys.stderr)
    print(f"排查建议：{advice}", file=sys.stderr)


def call_test_api(config: dict[str, object]) -> str:
    api_key = str(config["api_key"])
    client = OpenAI(
        api_key=api_key,
        base_url=str(config["base_url"]),
        timeout=float(config["timeout"]),
        max_retries=0,
    )

    extra_body = None
    if bool(config["enable_thinking"]):
        extra_body = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(
        model=str(config["model"]),
        messages=[{"role": "user", "content": TEST_MESSAGE}],
        stream=False,
        reasoning_effort=str(config["reasoning_effort"]),
        extra_body=extra_body,
    )

    if not response.choices:
        raise RuntimeError("API 返回成功，但 choices 为空。")
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError("API 返回成功，但模型回复内容为空。")
    return content.strip()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        config = load_config()
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2

    print("正在测试 LLM API 连接……")
    print(f"服务地址：{config['base_url']}")
    print(f"模型：{config['model']}")
    print("API Key：已读取（不会显示）")

    try:
        reply = call_test_api(config)
    except Exception as error:
        print_api_error(error, str(config["api_key"]))
        return 1

    print("模型回复：")
    print(reply)
    print("LLM API 连通性测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
