"""사례 복기 — 같은 기업을 여러 기준일로 실행해 "그 시점에 공개된 자료만으로 무엇이 보였나"를 시간순으로 본다.

    python scripts/run_case.py --code 123456 --dates 20240331,20240630,20240930,20241231,20250331

각 기준일마다 도구는 그 날짜 이전 접수분만 반환하므로, 결과는 사후 지식이 섞이지 않은 복기가 된다.
결과: reports/<code>/timeline.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.config import REPORTS_DIR
from scripts.run_monitor import run_one


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--code", required=True)
    p.add_argument("--dates", required=True, help="쉼표로 구분한 기준일 목록 (오름차순)")
    p.add_argument("--max-steps", type=int, default=None)
    a = p.parse_args()

    rows = []
    for asof in [d.strip() for d in a.dates.split(",") if d.strip()]:
        r = run_one(a.code, asof, a.max_steps)
        res, v = r["result"], r["verification"]
        memo = res["memo"]
        rows.append({
            "asof": asof,
            "report": f"{res['snapshot'].get('report', {}).get('bsns_year', '')} {res['snapshot'].get('report', {}).get('reprt_name', '')}",
            "repayment": ", ".join(res["pattern"]["repayment_signals"]) or "—",
            "market": ", ".join(res["pattern"]["market_signals"]) or "—",
            "relation": (memo.get("assessment") or {}).get("relation", "—"),
            "priority": memo.get("priority", "—"),
            "open_items": len(memo.get("open_items") or []),
            "verified": "통과" if v["ok"] else "실패",
            "tools": sum(1 for t in res["trace"] if t.get("action") == "tool_call"),
        })

    out = REPORTS_DIR / a.code / "timeline.md"
    lines = [f"# 사례 복기 타임라인 — {rows and r['result']['company']} ({a.code})", "",
             "각 행은 해당 기준일 이전에 공개된 자료만으로 실행한 결과다. 이후에 알려진 사실은 반영되지 않았다.", "",
             "| 기준일 | 최신 보고서 | 상환능력 신호 | 시장 신호 | 관계 | 우선순위 | 미확인 항목 | 검증 | 도구 호출 |",
             "|---|---|---|---|---|---|---:|---|---:|"]
    for r in rows:
        lines.append(f"| {r['asof']} | {r['report']} | {r['repayment']} | {r['market']} | {r['relation']} | {r['priority']} | {r['open_items']} | {r['verified']} | {r['tools']} |")
    lines += ["", "메모 원문: 같은 폴더의 `<기준일>_memo.md`", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
