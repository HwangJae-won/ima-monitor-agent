"""대조군 — 도구 없이, 같은 자료를 한 번에 주고 메모를 쓰게 한다.

Agent 가 '조사(추가 조회·방향 전환)'를 해서 얻는 것이 있는지 비교하기 위한 기준선이다.
같은 JSON 형식·같은 검증을 적용하므로 결과를 나란히 놓고 볼 수 있다.

    python scripts/baseline.py --code 005930 --asof 20251015
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.agent import SYSTEM_PROMPT
from monitor.config import REPORTS_DIR, today_ymd
from monitor.dart_client import DARTClient
from monitor.kis_client import KISClient
from monitor.llm import LLM, parse_json_block
from monitor.report import render
from monitor.signals import detect, summarize
from monitor.tools import Toolbox, compact_for_llm
from monitor.verify import verify


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--code", required=True)
    p.add_argument("--asof", default=today_ymd())
    a = p.parse_args()

    tb = Toolbox(KISClient(), DARTClient())
    snapshot = tb.get_financial_snapshot(a.code, a.asof)
    market = tb.get_market_signals(a.code, a.asof)
    disclosures = tb.get_disclosures(a.code, a.asof, 180)
    signals = detect(snapshot, market)
    pattern = summarize(signals)

    llm = LLM()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(max_steps=0) + "\n(대조군 실행: 도구를 호출할 수 없습니다. 아래 자료만으로 메모를 작성하세요.)"},
        {"role": "user", "content": (
            f"기업: {snapshot.get('company')} ({a.code})\n기준일: {a.asof}\n\n[변화 신호]\n{json.dumps(signals, ensure_ascii=False)}\n"
            f"[패턴] {json.dumps(pattern, ensure_ascii=False)}\n\n[재무 스냅샷]\n{compact_for_llm(snapshot)}\n\n"
            f"[시장 신호]\n{compact_for_llm(market)}\n\n[최근 180일 공시]\n{compact_for_llm(disclosures, 8000)}\n\nJSON 메모를 작성하세요."
        )},
    ]
    reply = llm.complete(messages, tools=None, force_text=True)
    memo = parse_json_block(reply.get("content", "")) or {"error": "파싱 실패", "raw": reply.get("content", "")}
    result = {"stock_code": a.code, "company": snapshot.get("company"), "asof": a.asof, "signals": signals, "pattern": pattern,
              "snapshot": snapshot, "market": market, "memo": memo, "evidence": tb.evidence,
              "trace": [{"step": 0, "actor": "code", "action": "observe", "signals": [s["code"] for s in signals], "pattern": pattern["pattern"]},
                        {"step": 1, "actor": "llm", "action": "final_memo", "parsed": "error" not in memo}],
              "usage": reply.get("_usage"), "elapsed_s": None, "model": llm.model + " (baseline, no tools)"}
    v = verify(memo, tb.evidence)
    out = REPORTS_DIR / a.code
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.asof}_baseline.md").write_text(render(result, v), encoding="utf-8")
    print(f"[baseline {a.code} @ {a.asof}] 우선순위 {memo.get('priority')} · 검증 {'통과' if v['ok'] else '실패'} · 오류 {len(v['errors'])} 경고 {len(v['warnings'])}")
    print(f"  → {out / (a.asof + '_baseline.md')}")


if __name__ == "__main__":
    main()
