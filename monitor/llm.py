"""LLM 호출 어댑터. 기본 Azure OpenAI, LLM_PROVIDER=openai 면 OpenAI 직접 호출.

Agent 는 이 모듈의 complete() 만 쓴다. 공급자를 바꾸려면 이 파일만 고치면 된다.
"""

from __future__ import annotations

import json
from typing import Any

from .config import env, require


class LLM:
    def __init__(self):
        self.provider = env("LLM_PROVIDER", "azure")
        if self.provider == "azure":
            from openai import AzureOpenAI

            self.client = AzureOpenAI(
                api_key=require("AZURE_OPENAI_API_KEY"),
                azure_endpoint=require("AZURE_OPENAI_ENDPOINT"),
                api_version=env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            )
            self.model = require("AZURE_OPENAI_DEPLOYMENT")
        else:
            from openai import OpenAI

            self.client = OpenAI(api_key=require("OPENAI_API_KEY"))
            self.model = env("OPENAI_MODEL", "gpt-4o-mini")

    def complete(self, messages: list[dict], tools: list[dict] | None = None, force_text: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools and not force_text:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        out: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for tc in msg.tool_calls
            ]
        usage = getattr(resp, "usage", None)
        out["_usage"] = {"prompt": getattr(usage, "prompt_tokens", None), "completion": getattr(usage, "completion_tokens", None)}
        return out


def parse_json_block(text: str) -> dict | None:
    """응답에서 JSON 객체를 뽑는다. 코드펜스·앞뒤 설명문을 허용."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
