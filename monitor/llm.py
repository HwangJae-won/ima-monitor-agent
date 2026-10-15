"""LLM 호출 어댑터.

LLM_PROVIDER
- azure        : Azure OpenAI, .env 의 AZURE_OPENAI_API_KEY 로 직접 호출 (openai SDK)
- azure_proxy  : Azure OpenAI, 키를 코드가 갖지 않음. 세션의 네트워크 시크릿(프록시)이
                 <리소스>.openai.azure.com 으로 나가는 요청에 api-key 헤더를 붙인다 (requests 로 REST 직접 호출)
- openai       : OpenAI 직접 호출

Agent 는 complete() 만 쓴다. 공급자를 바꾸려면 이 파일만 고치면 된다.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from .config import env, require


class LLM:
    def __init__(self):
        self.provider = env("LLM_PROVIDER", "azure")
        self.client = None
        if self.provider == "azure":
            from openai import AzureOpenAI

            self.client = AzureOpenAI(
                api_key=require("AZURE_OPENAI_API_KEY"),
                azure_endpoint=require("AZURE_OPENAI_ENDPOINT"),
                api_version=env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            )
            self.model = require("AZURE_OPENAI_DEPLOYMENT")
        elif self.provider == "azure_proxy":
            self.model = require("AZURE_OPENAI_DEPLOYMENT")
            self.url = (
                f"{require('AZURE_OPENAI_ENDPOINT').rstrip('/')}/openai/deployments/{self.model}/chat/completions"
                f"?api-version={env('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')}"
            )
        else:
            from openai import OpenAI

            self.client = OpenAI(api_key=require("OPENAI_API_KEY"))
            self.model = env("OPENAI_MODEL", "gpt-4o-mini")

    def complete(self, messages: list[dict], tools: list[dict] | None = None, force_text: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"messages": messages}
        if tools and not force_text:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.provider == "azure_proxy":
            return self._complete_rest(kwargs)
        resp = self.client.chat.completions.create(model=self.model, **kwargs)
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

    def _complete_rest(self, kwargs: dict) -> dict[str, Any]:
        # api-key 헤더는 보내지 않는다 — 프록시가 붙인다
        r = requests.post(self.url, headers={"content-type": "application/json"}, json=kwargs, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"Azure OpenAI {r.status_code}: {r.text[:300]}")
        body = r.json()
        msg = body["choices"][0]["message"]
        out: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            out["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["function"]["name"], "arguments": tc["function"].get("arguments") or "{}"}}
                for tc in msg["tool_calls"]
            ]
        usage = body.get("usage", {}) or {}
        out["_usage"] = {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens")}
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
