"""메모 검증 — LLM 출력이 도구 결과 안에서만 말했는지 코드로 확인한다.

검사 항목
1. 인용한 근거 id 가 실제로 수집된 evidence 에 있는가
2. 메모에 쓴 숫자가 evidence 데이터 어딘가에 존재하는가 (반올림 허용)
3. 근거 id 가 없는 주장이 있는가
4. 시장 신호를 상환능력 악화의 원인·증거로 단정한 문장이 있는가 (휴리스틱 경고)
5. '조달 완료' 표현이 있는데 완료 공시 근거가 없는가
"""

from __future__ import annotations

import re
from typing import Any

_NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
_COUNT_UNIT = re.compile(r"\s?(거래일|영업일|개월|분기|일|주|월|년|회|건|번|차|호|개|종목|스텝)")
_MARKET_WORDS = ("주가", "공매도", "순매도", "거래량", "신용잔고", "낙폭", "하락")
_REPAY_WORDS = ("상환능력", "상환 능력", "채무상환", "부실", "디폴트", "상환이 어렵", "갚지 못")
_CAUSAL = ("때문에", "으로 인해", "로 인해", "따라서", "이므로", "증거", "입증", "보여준다", "확인된다")
_COMPLETION_WORDS = ("조달 완료", "조달이 완료", "발행 완료", "납입 완료", "자금을 확보")


def _numbers_in(obj: Any, acc: set[float]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _numbers_in(v, acc)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            try:
                acc.add(float(m.replace(",", "")))
            except ValueError:
                pass


def _close(a: float, pool: set[float]) -> bool:
    if a in pool:
        return True
    for b in pool:
        if b == 0:
            continue
        if abs(a - b) / abs(b) <= 0.006:  # 0.6% — 소수점 반올림·억 단위 환산 허용
            return True
        # 억/백만 단위 환산 (예: 12,345,678,000 → 123.5억)
        for scale in (1e8, 1e6, 1e4, 1e3):
            if abs(a * scale - b) / abs(b) <= 0.006 or abs(a - b * scale) / max(abs(a), 1e-9) <= 0.006:
                return True
    return False


def _texts(memo: dict) -> list[tuple[str, str, list[str]]]:
    out = []
    for section in ("observed_changes", "repayment_evidence", "market_signals"):
        for item in memo.get(section, []) or []:
            if isinstance(item, dict):
                out.append((section, str(item.get("text", "")), list(item.get("evidence", []) or [])))
    a = memo.get("assessment", {}) or {}
    out.append(("assessment", str(a.get("reasoning", "")), list(memo.get("evidence_ids_used", []) or [])))
    out.append(("assessment", str(a.get("counter_evidence", "")), list(memo.get("evidence_ids_used", []) or [])))
    return out


def verify(memo: dict, evidence: dict[str, dict]) -> dict:
    if not memo or "error" in memo:
        return {"ok": False, "errors": ["메모 없음"], "warnings": [], "stats": {}}

    pool: set[float] = set()
    for ev in evidence.values():
        _numbers_in(ev.get("data"), pool)
        _numbers_in(ev.get("date"), pool)

    errors, warnings = [], []
    cited = set(memo.get("evidence_ids_used", []) or [])
    for _, _, ids in _texts(memo):
        cited.update(ids)
    unknown = sorted(i for i in cited if i not in evidence)
    if unknown:
        errors.append(f"수집되지 않은 근거 id 인용: {unknown}")

    n_claims, n_no_ev, n_nums, n_bad = 0, 0, 0, 0
    for section, text, ids in _texts(memo):
        if not text.strip():
            continue
        if section != "assessment":
            n_claims += 1
            if not ids:
                n_no_ev += 1
                warnings.append(f"[{section}] 근거 id 없는 주장: {text[:60]}")
        for mt in _NUM.finditer(text):
            m = mt.group(0)
            try:
                val = float(m.replace(",", ""))
            except ValueError:
                continue
            if abs(val) <= 12 or (1990 <= val <= 2100) or (19900101 <= val <= 21001231):
                continue  # 날짜·연도·소수의 개수는 제외
            if _COUNT_UNIT.match(text, mt.end()):
                continue  # "20일", "60거래일", "3개월" 같은 기간·횟수 표현은 지표값이 아님
            n_nums += 1
            if not _close(val, pool):
                n_bad += 1
                errors.append(f"[{section}] 근거에 없는 숫자 {m}: {text[:60]}")
        low = text.replace(" ", "")
        if any(w in low for w in (w.replace(" ", "") for w in _MARKET_WORDS)) and \
           any(w in low for w in (w.replace(" ", "") for w in _REPAY_WORDS)) and \
           any(c in low for c in _CAUSAL):
            warnings.append(f"[{section}] 시장 신호를 상환능력 판단의 근거로 단정했을 수 있음: {text[:70]}")
        if any(w.replace(" ", "") in low for w in _COMPLETION_WORDS):
            has_completion_ev = any(("발행실적" in (evidence.get(i, {}).get("title") or "") or "납입" in (evidence.get(i, {}).get("title") or "")) for i in ids)
            if not has_completion_ev:
                warnings.append(f"[{section}] '조달 완료' 표현에 발행실적·납입 공시 근거가 없음: {text[:70]}")

    rel = (memo.get("assessment", {}) or {}).get("relation")
    if rel not in ("consistent", "divergent", "insufficient"):
        errors.append(f"assessment.relation 값이 규격 밖: {rel}")
    if not memo.get("open_items"):
        warnings.append("open_items 가 비어 있음 — 공개 자료만으로 모든 것을 판단했다는 뜻이 되므로 재검토")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {"claims": n_claims, "claims_without_evidence": n_no_ev, "numbers_checked": n_nums,
                  "numbers_unsupported": n_bad, "evidence_cited": len(cited), "evidence_collected": len(evidence)},
    }
