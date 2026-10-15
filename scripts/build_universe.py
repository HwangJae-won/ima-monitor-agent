"""분석 대상 후보 만들기 — "기업금융(채권·CB) 으로 자금을 조달한 비금융 상장사".

IMA 가 투자할 법한 기업군이라는 '가정' 아래, 최근 N개월 동안
  - 증권신고서(채무증권) [DART 공시유형 C002] 을 냈거나
  - 전환사채권·신주인수권부사채권 발행결정 [주요사항보고서 B001] 을 낸
상장사를 DART 공시 목록에서 뽑는다. 금융업은 업종명 휴리스틱으로 제외한다.

    python scripts/build_universe.py --months 18 --out data/universe_candidates.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.config import DATA_DIR, ymd
from monitor.dart_client import DARTClient

_FINANCIAL = ("은행", "증권", "보험", "카드", "캐피탈", "금융", "자산운용", "저축", "투자", "리츠", "스팩", "기업인수목적", "신탁", "파이낸")
_CB_WORDS = ("전환사채권발행결정", "신주인수권부사채권발행결정", "교환사채권발행결정")


def _month_ranges(months: int):
    end = date.today()
    cur = end
    for _ in range(months):
        start = (cur.replace(day=1) - timedelta(days=1)).replace(day=1)
        yield ymd(start), ymd(cur)
        cur = start - timedelta(days=1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--months", type=int, default=18)
    p.add_argument("--out", default=str(DATA_DIR / "universe_candidates.csv"))
    a = p.parse_args()

    dart = DARTClient()
    listed = {r["corp_code"]: r for r in dart.corp_codes()}
    hits: dict[str, dict] = defaultdict(lambda: {"bond_rs": 0, "cb_bw": 0, "first": "99999999", "last": "00000000"})

    for bgn, end in _month_ranges(a.months):
        for detail, kind in (("C002", "bond_rs"), ("B001", "cb_bw")):
            page = 1
            while page <= 20:
                body = dart._get("list", {"bgn_de": bgn, "end_de": end, "pblntf_detail_ty": detail, "page_no": page, "page_count": 100})
                items = body.get("list", []) or []
                for it in items:
                    cc = it.get("corp_code")
                    if cc not in listed:
                        continue
                    nm = it.get("report_nm", "").replace(" ", "")
                    if kind == "cb_bw" and not any(w in nm for w in _CB_WORDS):
                        continue
                    h = hits[cc]
                    h[kind] += 1
                    h["first"] = min(h["first"], it["rcept_dt"])
                    h["last"] = max(h["last"], it["rcept_dt"])
                if page >= int(body.get("total_page", 1) or 1):
                    break
                page += 1
        print(f"{bgn}~{end}: 누적 후보 {len(hits)}")

    rows = []
    for cc, h in hits.items():
        c = listed[cc]
        if any(w in c["corp_name"] for w in _FINANCIAL):
            continue
        rows.append({"stock_code": c["stock_code"], "corp_name": c["corp_name"], "corp_code": cc,
                     "bond_registrations": h["bond_rs"], "cb_bw_decisions": h["cb_bw"], "first": h["first"], "last": h["last"]})
    rows.sort(key=lambda r: (-(r["bond_registrations"] + r["cb_bw_decisions"]), r["corp_name"]))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["stock_code"])
        w.writeheader()
        w.writerows(rows)
    print(f"비금융 상장사 후보 {len(rows)}곳 → {out}")
    print("상위 15:")
    for r in rows[:15]:
        print(f"  {r['stock_code']} {r['corp_name']}: 채무증권신고 {r['bond_registrations']}, CB/BW 결정 {r['cb_bw_decisions']}")


if __name__ == "__main__":
    main()
