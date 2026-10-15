"""기준일(as-of) 규칙: 도구는 기준일 이전에 공개된 자료만 돌려줘야 한다."""

from monitor.signals import detect, summarize


def test_financial_snapshot_uses_only_reports_filed_before_asof(toolbox):
    # 2025.08.14 반기보고서 접수 전인 8월 1일 기준 → 3월 사업보고서가 최신
    s = toolbox.get_financial_snapshot("000001", "20250801")
    assert s["report"]["rcept_dt"] == "20250320"
    assert s["data_public_since"] == "20250320"
    # 8월 20일 기준 → 반기보고서
    s2 = toolbox.get_financial_snapshot("000001", "20250820")
    assert s2["report"]["rcept_dt"] == "20250814"
    assert s2["metrics"]["ocf"] == -80
    assert s2["metrics"]["interest_coverage"] == round(50 / 60, 2)
    assert s2["metrics"]["short_term_debt"] == 500  # 단기차입금 400 + 유동성장기부채 100
    assert s2["metrics"]["cash_to_short_debt_pct"] == 20.0


def test_disclosures_exclude_future_filings(toolbox):
    d = toolbox.get_disclosures("000001", "20250820", lookback_days=120)
    titles = [f["title"] for f in d["filings"]]
    assert any("전환사채권발행결정" in t for t in titles)
    assert not any("회생절차" in t for t in titles)  # 9월 5일 접수분은 보이면 안 됨
    assert all(f["date"] <= "20250820" for f in d["filings"])
    # 9월 10일 기준에서는 보여야 함
    d2 = toolbox.get_disclosures("000001", "20250910", lookback_days=120, category="credit_event")
    assert any("회생절차" in f["title"] for f in d2["filings"])


def test_market_signals_exclude_future_prices(toolbox):
    m = toolbox.get_market_signals("000001", "20250815")
    assert m["price"]["last_date"] <= "20250815"
    assert m["price"]["return_20d_pct"] is not None and m["price"]["return_20d_pct"] > -5  # 하락 전
    m2 = toolbox.get_market_signals("000001", "20251015")
    assert m2["price"]["return_20d_pct"] < -20  # 하락 후


def test_funding_completion_status(toolbox):
    # 결정(6/10) 만 있고 실적(7/2) 전인 6월 말 기준 → 계획만 확인
    r = toolbox.check_funding_completion("000001", "20250625", since="20250601")
    assert r["status"].startswith("계획(결정) 공시만 확인")
    # 실적 공시 이후 → 조달 완료 확인
    r2 = toolbox.check_funding_completion("000001", "20250715", since="20250601")
    assert r2["status"] == "조달 완료 공시 확인"
    assert len(r2["completions"]) == 1


def test_signals_separate_repayment_and_market(toolbox):
    s = toolbox.get_financial_snapshot("000001", "20251015")
    m = toolbox.get_market_signals("000001", "20251015")
    sig = detect(s, m)
    codes = {x["code"] for x in sig}
    assert {"OCF_NEGATIVE", "SHORT_DEBT_UP", "ICR_BELOW_1", "CASH_SHORT_OF_DEBT", "CASH_DOWN"} <= codes
    assert "PRICE_DROP_20D" in codes
    assert summarize(sig)["pattern"] == "both"
    for x in sig:
        assert x["evidence"], f"{x['code']} 에 근거 id 가 없음"
        assert x["category"] in ("repayment", "market")


def test_evidence_ids_are_registered(toolbox):
    toolbox.get_financial_snapshot("000001", "20251015")
    toolbox.get_disclosures("000001", "20251015")
    toolbox.get_market_signals("000001", "20251015")
    assert all(k.startswith("E-") for k in toolbox.evidence)
    assert any(k.startswith("E-D-") for k in toolbox.evidence) and any(k.startswith("E-K-") for k in toolbox.evidence)
