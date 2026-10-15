"""기업 1곳, 기준일 1개에 대해 조사 Agent 를 실행하고 메모를 저장한다.

    python scripts/run_monitor.py --code 005930 --asof 20251015
    python scripts/run_monitor.py --code 005930 --asof 20251015 --max-steps 4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.agent import InvestigationAgent
from monitor.config import REPORTS_DIR, today_ymd
from monitor.dart_client import DARTClient
from monitor.kis_client import KISClient
from monitor.report import render
from monitor.tools import Toolbox
from monitor.verify import verify


def run_one(code: str, asof: str, max_steps: int | None = None, out_dir: Path | None = None) -> dict:
    tb = Toolbox(KISClient(), DARTClient())
    agent = InvestigationAgent(tb, max_steps=max_steps)
    result = agent.run(code, asof)
    v = verify(result["memo"], result["evidence"])
    md = render(result, v)

    out = (out_dir or REPORTS_DIR) / code
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{asof}_memo.md").write_text(md, encoding="utf-8")
    (out / f"trace_{asof}.json").write_text(
        json.dumps({k: v_ for k, v_ in result.items() if k not in ("snapshot", "market")} | {"verification": v},
                   ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    print(f"[{code} @ {asof}] {result['company']} · 신호 {[s['code'] for s in result['signals']]} · "
          f"우선순위 {result['memo'].get('priority')} · 검증 {'통과' if v['ok'] else '실패'} · "
          f"도구 {sum(1 for t in result['trace'] if t.get('action') == 'tool_call')}회 · {result['elapsed_s']}s")
    print(f"  → {out / (asof + '_memo.md')}")
    return {"result": result, "verification": v, "markdown": md}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--code", required=True, help="종목코드 6자리")
    p.add_argument("--asof", default=today_ymd(), help="기준일 YYYYMMDD (기본 오늘)")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--out", default=None, help="출력 디렉터리 (기본 reports/)")
    a = p.parse_args()
    run_one(a.code, a.asof, a.max_steps, Path(a.out) if a.out else None)


if __name__ == "__main__":
    main()
