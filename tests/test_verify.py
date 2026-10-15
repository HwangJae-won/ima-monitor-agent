from monitor.verify import verify

EVIDENCE = {
    "E-D-1-FS": {"id": "E-D-1-FS", "source": "DART", "date": "20250814", "title": "반기 재무제표",
                 "data": {"metrics": {"ocf": -80.0, "short_term_debt": 500.0, "short_term_debt_change_pct": 42.9}}},
    "E-K-PRICE-1": {"id": "E-K-PRICE-1", "source": "KIS", "date": "20251015", "title": "가격", "data": {"return_20d_pct": -26.3}},
}


def _memo(**over):
    base = {
        "observed_changes": [{"text": "단기차입금이 전기 대비 42.9% 증가해 500 수준", "evidence": ["E-D-1-FS"]}],
        "repayment_evidence": [{"text": "영업활동현금흐름 -80", "evidence": ["E-D-1-FS"]}],
        "market_signals": [{"text": "20일 수익률 -26.3%", "evidence": ["E-K-PRICE-1"]}],
        "assessment": {"relation": "consistent", "reasoning": "재무 악화와 시장 반응이 같은 방향", "counter_evidence": ""},
        "open_items": [{"question": "차입금 만기 일정", "why": "주석 필요", "source_needed": "재무제표 주석"}],
        "priority": "review",
        "evidence_ids_used": ["E-D-1-FS", "E-K-PRICE-1"],
    }
    base.update(over)
    return base


def test_clean_memo_passes():
    v = verify(_memo(), EVIDENCE)
    assert v["ok"], v
    assert v["stats"]["numbers_unsupported"] == 0


def test_unknown_evidence_id_fails():
    v = verify(_memo(evidence_ids_used=["E-D-1-FS", "E-D-999"]), EVIDENCE)
    assert not v["ok"] and any("E-D-999" in e for e in v["errors"])


def test_number_not_in_evidence_fails():
    v = verify(_memo(repayment_evidence=[{"text": "영업활동현금흐름이 -1,234 로 악화", "evidence": ["E-D-1-FS"]}]), EVIDENCE)
    assert not v["ok"] and any("1,234" in e for e in v["errors"])


def test_scaled_number_allowed():
    ev = {"E-D-1-FS": {"id": "E-D-1-FS", "source": "DART", "date": "20250814", "title": "x", "data": {"cash": 12_345_678_000.0}}}
    v = verify(_memo(observed_changes=[{"text": "현금성자산 123.5억", "evidence": ["E-D-1-FS"]}], repayment_evidence=[], market_signals=[],
                     evidence_ids_used=["E-D-1-FS"]), ev)
    assert v["stats"]["numbers_unsupported"] == 0, v


def test_market_causal_claim_warns():
    v = verify(_memo(assessment={"relation": "consistent", "reasoning": "주가 하락 때문에 상환능력이 악화됐다", "counter_evidence": ""}), EVIDENCE)
    assert any("단정" in w for w in v["warnings"])


def test_completion_claim_without_completion_evidence_warns():
    v = verify(_memo(observed_changes=[{"text": "전환사채로 자금 조달 완료", "evidence": ["E-D-1-FS"]}]), EVIDENCE)
    assert any("조달 완료" in w for w in v["warnings"])
