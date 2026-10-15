"""기업금융 사후 모니터링 조사 Agent.

동작
1. (코드) 기준일 시점의 재무 스냅샷·시장 신호를 만들고 변화 신호를 탐지한다.
2. (Agent) 신호를 보고 "무엇을 더 확인해야 하는가"를 정해 도구를 호출한다.
   - 차입금 증가 → 자금조달 결정 공시가 있는가 → 있다면 조달이 완료됐는가
   - 주가 급락 → 재무에도 변화가 있는가, 아니면 시장 반응만인가
   - 근거가 없으면 결론 내지 않고 '확인 불가' 로 남긴다
3. (Agent) 관측 사실 / 상환능력 근거 / 시장 신호 / 종합 검토 / 추가 확인 사항을 JSON 메모로 낸다.
4. (코드) verify.py 가 메모의 숫자와 근거 id 를 도구 결과와 대조한다.

멀티에이전트가 아니다. Agent 하나 + 도구 4개. 도구 호출 경로가 신호와 중간 결과에 따라 달라지는 것이 핵심이다.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .config import env, shift
from .llm import LLM, parse_json_block
from .signals import detect, summarize
from .tools import TOOL_SPECS, Toolbox, compact_for_llm

SYSTEM_PROMPT = """당신은 증권사 기업금융 투자자산 모니터링 담당자를 돕는 조사 보조 Agent 입니다.
투자(대출·채권·지분)한 기업의 상태가 투자 시점과 달라졌는지, 달라졌다면 무엇을 더 확인해야 하는지를 조사합니다.

원칙
1. 숫자는 도구 결과에 있는 값만 인용합니다. 계산·추정하지 않습니다.
2. 모든 주장에는 근거 id(E-D-…, E-K-…)를 붙입니다. 근거 id 없는 주장은 쓰지 않습니다.
3. 주가 하락·공매도 증가·순매도는 '시장의 반응'입니다. 그것만으로 상환능력이 악화됐다고 단정하지 않습니다.
   상환능력은 영업현금흐름, 차입금 규모와 만기, 현금성자산, 이자부담, 자금조달 공시로 판단합니다.
4. 자금조달 '결정'(발행결정·증권신고서)은 계획입니다. 납입·발행실적 공시를 확인하기 전에는 '조달 완료'라고 쓰지 않습니다.
5. 도구 결과에 없는 것은 '확인 불가'로 남기고, 어떤 자료(재무제표 주석, 내부 여신자료, 추가 공시)가 있어야 판단할 수 있는지 적습니다.
6. 조사는 최대 {max_steps}번의 도구 호출 안에서 끝냅니다. 더 볼 이유가 없으면 바로 메모를 작성합니다.

조사 순서(권장)
- 상환능력 신호(차입금 증가, 현금흐름 악화)가 있으면 → get_disclosures(category=funding) → 결정 공시가 있으면 check_funding_completion
- 신용사건 가능성이 있으면 → get_disclosures(category=credit_event), get_disclosures(category=audit)
- 시장 신호만 있고 재무 신호가 없으면 → 시장 전체 요인인지 판단할 수 없음을 명시하고, 최근 공시에서 원인이 될 사건이 있는지 확인
- 전기 대비 변화의 맥락이 필요하면 → get_financial_snapshot(과거 asof)

최종 메모는 반드시 아래 JSON 형식 하나만 출력합니다(설명문 없이).
{{
  "observed_changes": [{{"text": "...", "evidence": ["E-..."]}}],
  "repayment_evidence": [{{"text": "...", "evidence": ["E-..."]}}],
  "market_signals": [{{"text": "...", "evidence": ["E-..."]}}],
  "assessment": {{
    "relation": "consistent | divergent | insufficient",
    "reasoning": "두 종류의 신호가 같은 방향인지, 엇갈리는지, 판단하기에 부족한지",
    "counter_evidence": "반대로 해석할 수 있는 근거가 있으면 적는다"
  }},
  "open_items": [{{"question": "...", "why": "...", "source_needed": "재무제표 주석 | 추가 공시 | 내부 여신·상환 자료 | 경영진 확인"}}],
  "priority": "watch | review | escalate",
  "evidence_ids_used": ["E-..."]
}}
"""


class InvestigationAgent:
    def __init__(self, toolbox: Toolbox, llm: LLM | None = None, max_steps: int | None = None):
        self.tb = toolbox
        self.llm = llm or LLM()
        self.max_steps = max_steps or int(env("AGENT_MAX_STEPS", "6"))

    # ── 도구 디스패치 (stock_code·asof 는 Agent 가 바꿀 수 없게 고정) ──
    def _call_tool(self, name: str, args: dict, stock_code: str, asof: str) -> dict:
        if name == "get_disclosures":
            return self.tb.get_disclosures(stock_code, asof, int(args.get("lookback_days", 180)), args.get("category"))
        if name == "check_funding_completion":
            since = args.get("since") or shift(asof, -365)
            return self.tb.check_funding_completion(stock_code, asof, min(since, asof))
        if name == "get_financial_snapshot":
            past = args.get("asof", asof)
            return self.tb.get_financial_snapshot(stock_code, min(past, asof))  # 미래 기준일 금지
        if name == "get_market_signals":
            return self.tb.get_market_signals(stock_code, asof, int(args.get("lookback_days", 120)))
        return {"error": f"알 수 없는 도구 {name}"}

    def run(self, stock_code: str, asof: str) -> dict[str, Any]:
        t0 = time.time()
        trace: list[dict] = []

        # 1. 코드가 먼저 관측한다
        snapshot = self.tb.get_financial_snapshot(stock_code, asof)
        market = self.tb.get_market_signals(stock_code, asof)
        signals = detect(snapshot, market)
        pattern = summarize(signals)
        trace.append({"step": 0, "actor": "code", "action": "observe",
                      "signals": [s["code"] for s in signals], "pattern": pattern["pattern"]})

        company = snapshot.get("company") or stock_code
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(max_steps=self.max_steps)},
            {"role": "user", "content": (
                f"기업: {company} ({stock_code})\n기준일: {asof} — 이 날짜 이전에 공개된 자료만 사용 가능합니다.\n\n"
                f"[코드가 탐지한 변화 신호]\n{json.dumps(signals, ensure_ascii=False)}\n"
                f"[신호 패턴] {json.dumps(pattern, ensure_ascii=False)}\n\n"
                f"[재무 스냅샷]\n{compact_for_llm(snapshot)}\n\n"
                f"[시장 신호]\n{compact_for_llm(market)}\n\n"
                "무엇을 더 확인해야 하는지 정하고 도구를 호출하세요. 확인이 끝나면 JSON 메모를 작성하세요."
            )},
        ]

        # 2. Agent 조사 루프
        memo: dict | None = None
        usage = {"prompt": 0, "completion": 0}
        for step in range(1, self.max_steps + 2):
            force_text = step > self.max_steps
            if force_text:
                messages.append({"role": "user", "content": "도구 호출 한도에 도달했습니다. 지금까지의 근거로 JSON 메모를 작성하세요. 확인 못 한 것은 open_items 에 남기세요."})
            reply = self.llm.complete(messages, TOOL_SPECS, force_text=force_text)
            for k in usage:
                usage[k] += reply.get("_usage", {}).get(k) or 0
            assistant_msg = {k: v for k, v in reply.items() if not k.startswith("_")}
            messages.append(assistant_msg)

            if reply.get("tool_calls"):
                for tc in reply["tool_calls"]:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    t1 = time.time()
                    try:
                        result = self._call_tool(name, args, stock_code, asof)
                    except Exception as e:  # 도구 실패는 Agent 에게 알려 '확인 불가'로 처리하게 한다
                        result = {"error": f"{type(e).__name__}: {e}"}
                    trace.append({"step": step, "actor": "agent", "action": "tool_call", "tool": name, "args": args,
                                  "result_keys": list(result.keys())[:12], "evidence_count": len(result.get("evidence", [])),
                                  "status": result.get("status"), "error": result.get("error"), "ms": round((time.time() - t1) * 1000)})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": compact_for_llm(result)})
                continue

            memo = parse_json_block(reply.get("content", ""))
            trace.append({"step": step, "actor": "agent", "action": "final_memo", "parsed": memo is not None})
            if memo is None and not force_text:
                messages.append({"role": "user", "content": "출력이 JSON 형식이 아닙니다. 지정한 JSON 형식 하나만 다시 출력하세요."})
                continue
            break

        return {
            "stock_code": stock_code,
            "company": company,
            "asof": asof,
            "signals": signals,
            "pattern": pattern,
            "snapshot": snapshot,
            "market": market,
            "memo": memo or {"error": "메모 파싱 실패", "raw": messages[-1].get("content", "")},
            "evidence": self.tb.evidence,
            "trace": trace,
            "usage": usage,
            "elapsed_s": round(time.time() - t0, 1),
            "model": self.llm.model,
        }
