"""변화 탐지 — 코드가 계산한다. Agent 는 여기서 나온 신호를 출발점으로 조사를 시작한다.

두 종류를 분리해서 낸다.
- repayment: 상환능력과 직접 관련된 재무 변화 (현금흐름, 차입금, 이자보상, 유동성)
- market   : 시장 참가자의 반응 (주가, 변동성, 신용잔고, 공매도, 수급)
시장 신호는 '확인할 이유'이지 '상환능력 악화의 증거'가 아니다.
"""

from __future__ import annotations


def detect(snapshot: dict, market: dict) -> list[dict]:
    sig: list[dict] = []
    m = snapshot.get("metrics", {}) or {}
    fs_ev = snapshot.get("evidence", [])[:1]

    def add(code, category, text, values, evidence):
        sig.append({"code": code, "category": category, "text": text, "values": values, "evidence": evidence})

    # ── 상환능력 ──
    if m.get("ocf") is not None and m["ocf"] < 0:
        add("OCF_NEGATIVE", "repayment", "영업활동현금흐름이 음(-)", {"ocf": m["ocf"]}, fs_ev)
    if m.get("ocf_change_pct") is not None and m["ocf_change_pct"] <= -30:
        add("OCF_DETERIORATED", "repayment", "영업활동현금흐름이 전기 대비 30% 이상 감소", {"ocf_change_pct": m["ocf_change_pct"]}, fs_ev)
    if m.get("short_term_debt_change_pct") is not None and m["short_term_debt_change_pct"] >= 20:
        add("SHORT_DEBT_UP", "repayment", "단기차입금(유동성장기부채 포함)이 전기 대비 20% 이상 증가",
            {"short_term_debt_change_pct": m["short_term_debt_change_pct"], "short_term_debt": m.get("short_term_debt")}, fs_ev)
    if m.get("interest_coverage") is not None and m["interest_coverage"] < 1:
        add("ICR_BELOW_1", "repayment", "이자보상배율 1 미만 (영업이익으로 이자를 못 갚는 수준)",
            {"interest_coverage": m["interest_coverage"], "note": m.get("interest_coverage_note")}, fs_ev)
    if m.get("cash_to_short_debt_pct") is not None and m["cash_to_short_debt_pct"] < 50:
        add("CASH_SHORT_OF_DEBT", "repayment", "현금성자산이 1년 내 만기 차입금의 절반 미만",
            {"cash_to_short_debt_pct": m["cash_to_short_debt_pct"]}, fs_ev)
    if m.get("cash_change_pct") is not None and m["cash_change_pct"] <= -30:
        add("CASH_DOWN", "repayment", "현금성자산이 전기 대비 30% 이상 감소", {"cash_change_pct": m["cash_change_pct"]}, fs_ev)
    if m.get("capital_impairment"):
        add("CAPITAL_IMPAIRMENT", "repayment", "자본총계 0 이하 (완전자본잠식)", {}, fs_ev)
    if m.get("operating_income") is not None and m["operating_income"] < 0:
        add("OPERATING_LOSS", "repayment", "영업손실", {"operating_income": m["operating_income"]}, fs_ev)

    # ── 시장 ──
    p = market.get("price", {}) or {}
    pe = [e for e in market.get("evidence", []) if "PRICE" in e]
    if p.get("return_20d_pct") is not None and p["return_20d_pct"] <= -20:
        add("PRICE_DROP_20D", "market", "20거래일 수익률 -20% 이하", {"return_20d_pct": p["return_20d_pct"]}, pe)
    if p.get("max_drawdown_60d_pct") is not None and p["max_drawdown_60d_pct"] <= -35:
        add("DRAWDOWN_60D", "market", "60거래일 최대낙폭 -35% 이하", {"max_drawdown_60d_pct": p["max_drawdown_60d_pct"]}, pe)
    if p.get("volume_ratio_5d_vs_60d") is not None and p["volume_ratio_5d_vs_60d"] >= 3:
        add("VOLUME_SPIKE", "market", "최근 5일 거래량이 60일 평균의 3배 이상", {"volume_ratio_5d_vs_60d": p["volume_ratio_5d_vs_60d"]}, pe)
    c = market.get("credit_balance", {}) or {}
    if c.get("loan_balance_shares_change_20d_pct") is not None and c["loan_balance_shares_change_20d_pct"] >= 30:
        add("CREDIT_BALANCE_UP", "market", "신용융자 잔고 주수가 20일 전 대비 30% 이상 증가 (반대매매 위험 상승)",
            {"loan_balance_shares_change_20d_pct": c["loan_balance_shares_change_20d_pct"]},
            [e for e in market["evidence"] if "CREDIT" in e])
    s = market.get("short_sale", {}) or {}
    if s.get("short_vol_ratio_avg_20d_pct") is not None and s.get("short_vol_ratio_avg_prior_20d_pct") is not None \
            and s["short_vol_ratio_avg_20d_pct"] >= max(5, s["short_vol_ratio_avg_prior_20d_pct"] * 2):
        add("SHORT_SALE_UP", "market", "공매도 거래량 비중이 직전 20일 대비 2배 이상",
            {"recent": s["short_vol_ratio_avg_20d_pct"], "prior": s["short_vol_ratio_avg_prior_20d_pct"]},
            [e for e in market["evidence"] if "SHORT" in e])
    i = market.get("investors", {}) or {}
    if i.get("institution_net_sell_days_20d", 0) >= 15 or i.get("foreign_net_sell_days_20d", 0) >= 15:
        add("PERSISTENT_NET_SELL", "market", "기관 또는 외국인이 20일 중 15일 이상 순매도",
            {"institution_net_sell_days_20d": i.get("institution_net_sell_days_20d"),
             "foreign_net_sell_days_20d": i.get("foreign_net_sell_days_20d")},
            [e for e in market["evidence"] if "INVESTOR" in e])
    return sig


def summarize(signals: list[dict]) -> dict:
    rep = [s for s in signals if s["category"] == "repayment"]
    mkt = [s for s in signals if s["category"] == "market"]
    if rep and mkt:
        pattern = "both"       # 상환능력 신호 + 시장 반응 동시 → 공시에서 원인 확인
    elif rep:
        pattern = "repayment_only"  # 주가는 조용한데 재무는 악화 → 만기 대응 가능성 확인
    elif mkt:
        pattern = "market_only"     # 주가만 움직임 → 시장 전체 요인인지, 재무에도 변화가 있는지 확인
    else:
        pattern = "none"
    return {"pattern": pattern, "repayment_signals": [s["code"] for s in rep], "market_signals": [s["code"] for s in mkt]}
