from __future__ import annotations

import sys
from dataclasses import dataclass

from openai import NOT_GIVEN, APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from src.config import Settings


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    finish_reason: str
    completion_tokens: int | None
    max_tokens: int


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )

    def complete(self, messages: list[dict[str, str]], max_tokens: int) -> LLMCompletion:
        reasoning_effort = NOT_GIVEN
        extra_body = None
        if self.settings.enable_thinking:
            reasoning_effort = self.settings.reasoning_effort
            extra_body = {"thinking": {"type": "enabled"}}
        else:
            extra_body = {"thinking": {"type": "disabled"}}

        response = None
        retryable_errors = (APITimeoutError, RateLimitError, APIConnectionError)
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    stream=False,
                    temperature=0.2,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                    extra_body=extra_body,
                )
                break
            except retryable_errors as error:
                if attempt == 1:
                    raise
                if isinstance(error, APITimeoutError):
                    reason = "请求超时"
                elif isinstance(error, RateLimitError):
                    reason = "请求频率受限（HTTP 429）"
                else:
                    reason = "网络连接失败"
                print(f"{reason}，正在进行唯一一次重试……", file=sys.stderr)

        if response is None:
            raise RuntimeError("LLM 请求未返回结果。")
        if not response.choices:
            raise RuntimeError("LLM 返回成功，但 choices 为空。")
        choice = response.choices[0]
        if choice.finish_reason is None:
            raise RuntimeError("API响应中缺少 finish_reason，无法安全判断输出是否完整。")
        completion_tokens = None
        if response.usage is not None:
            completion_tokens = response.usage.completion_tokens
        return LLMCompletion(
            content=(choice.message.content or "").strip(),
            finish_reason=str(choice.finish_reason),
            completion_tokens=completion_tokens,
            max_tokens=max_tokens,
        )
