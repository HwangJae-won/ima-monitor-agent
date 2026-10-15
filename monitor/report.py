"""조사 결과를 담당자가 읽는 마크다운 메모로 렌더링한다. 섹션 구성은 업무 검토 메모 형식을 따른다."""

from __future__ import annotations

import json
from datetime import datetime


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1e8:
            return f"{v / 1e8:,.1f}억"
        if abs(v) >= 1e4 and float(v).is_integer():
            return f"{int(v):,}"
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, bool):
        return "예" if v else "아니오"
    return str(v)


def _items(items: list[dict]) -> str:
    if not items:
        return "- (없음)\n"
    out = ""
    for it in items:
        ev = ", ".join(f"`{e}`" for e in (it.get("evidence") or []))
        out += f"- {it.get('text', '')} {('[' + ev + ']') if ev else ''}\n"
    return out


def render(result: dict, verification: dict) -> str:
    memo = result.get("memo", {}) or {}
    m = (result.get("snapshot", {}) or {}).get("metrics", {}) or {}
    rep = (result.get("snapshot", {}) or {}).get("report", {}) or {}
    price = (result.get("market", {}) or {}).get("price", {}) or {}
    a = memo.get("assessment", {}) or {}
    rel_ko = {"consistent": "일치 (같은 방향)", "divergent": "엇갈림", "insufficient": "판단 근거 부족"}.get(a.get("relation"), a.get("relation", "—"))
    prio_ko = {"watch": "관찰 유지", "review": "추가 확인", "escalate": "즉시 검토"}.get(memo.get("priority"), memo.get("priority", "—"))

    lines = [
        f"# 사후 모니터링 조사 메모 — {result.get('company')} ({result.get('stock_code')})",
        "",
        f"- 기준일: **{result['asof']}** (이 날짜 이전에 공개된 자료만 사용)",
        f"- 최신 정기보고서: {rep.get('bsns_year', '')} {rep.get('reprt_name', '')} ({rep.get('fs_div', '')}), 접수일 {rep.get('rcept_dt', '—')}",
        f"- 검토 우선순위(제안): **{prio_ko}** · 신호 패턴: `{result.get('pattern', {}).get('pattern')}`",
        f"- 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')} · 모델 {result.get('model')} · 도구 호출 {sum(1 for t in result['trace'] if t.get('action') == 'tool_call')}회 · {result.get('elapsed_s')}s",
        "",
        "> 이 메모는 공개 자료(DART·KIS API)만으로 만든 업무 시뮬레이션이며, 실제 투자자산·내부 여신 정보를 반영하지 않습니다. 최종 판단은 담당자가 합니다.",
        "",
        "## 1. 새롭게 관측된 변화",
        _items(memo.get("observed_changes", [])),
        "## 2. 상환능력 관련 근거",
        "| 지표 | 값 | 전기 대비 |",
        "|---|---:|---:|",
        f"| 영업활동현금흐름 | {_fmt(m.get('ocf'))} | {_fmt(m.get('ocf_change_pct'))}% |",
        f"| 현금및현금성자산 | {_fmt(m.get('cash'))} | {_fmt(m.get('cash_change_pct'))}% |",
        f"| 1년 내 만기 차입금(단기+유동성장기) | {_fmt(m.get('short_term_debt'))} | {_fmt(m.get('short_term_debt_change_pct'))}% |",
        f"| 총차입금 | {_fmt(m.get('total_debt'))} | {_fmt(m.get('total_debt_change_pct'))}% |",
        f"| 현금 / 1년 내 만기 차입금 | {_fmt(m.get('cash_to_short_debt_pct'))}% | |",
        f"| 이자보상배율 | {_fmt(m.get('interest_coverage'))} | {m.get('interest_coverage_note', '')} |",
        f"| 유동비율 | {_fmt(m.get('current_ratio_pct'))}% | |",
        f"| 부채비율 | {_fmt(m.get('debt_to_equity_pct'))}% | |",
        "",
        _items(memo.get("repayment_evidence", [])),
        "## 3. 시장 신호 (KIS API)",
        f"- 최근 종가 {_fmt(price.get('last_close'))} ({price.get('last_date', '—')}) · 20일 {_fmt(price.get('return_20d_pct'))}% · 60일 {_fmt(price.get('return_60d_pct'))}% · 60일 최대낙폭 {_fmt(price.get('max_drawdown_60d_pct'))}% · 변동성(연환산) {_fmt(price.get('volatility_20d_annualized_pct'))}%",
        _items(memo.get("market_signals", [])),
        "## 4. 종합 검토",
        f"- 두 신호의 관계: **{rel_ko}**",
        f"- 해석: {a.get('reasoning', '—')}",
        f"- 반대 근거: {a.get('counter_evidence') or '—'}",
        "",
        "## 5. 추가 확인 사항 (공개 자료로 판단하지 못한 것)",
    ]
    for it in memo.get("open_items", []) or []:
        lines.append(f"- **{it.get('question', '')}** — {it.get('why', '')} _(필요 자료: {it.get('source_needed', '—')})_")
    if not memo.get("open_items"):
        lines.append("- (없음)")

    lines += ["", "## 6. 출처·기준일", "| 근거 id | 출처 | 공개일 | 내용 |", "|---|---|---|---|"]
    used = set(memo.get("evidence_ids_used", []) or [])
    for sec in ("observed_changes", "repayment_evidence", "market_signals"):
        for it in memo.get(sec, []) or []:
            used.update(it.get("evidence", []) or [])
    for eid in sorted(used):
        ev = result["evidence"].get(eid)
        if not ev:
            lines.append(f"| `{eid}` | ? | ? | **수집되지 않은 근거 (검증 실패)** |")
            continue
        title = ev.get("title", "")
        link = f"[{title}]({ev['url']})" if ev.get("url") else title
        lines.append(f"| `{eid}` | {ev.get('source')} | {ev.get('date')} | {link} |")

    v = verification
    lines += ["", "## 7. 자동 검증 결과", f"- 통과 여부: **{'통과' if v.get('ok') else '실패'}** · {json.dumps(v.get('stats', {}), ensure_ascii=False)}"]
    for e in v.get("errors", []):
        lines.append(f"- ❌ {e}")
    for w in v.get("warnings", []):
        lines.append(f"- ⚠️ {w}")

    lines += ["", "## 8. 조사 과정 (trace)", "| step | 주체 | 행동 | 세부 |", "|---|---|---|---|"]
    for t in result["trace"]:
        if t["actor"] == "code":
            detail = f"신호 {t.get('signals')} · 패턴 {t.get('pattern')}"
        elif t["action"] == "tool_call":
            detail = f"`{t['tool']}` {json.dumps(t.get('args', {}), ensure_ascii=False)} → 근거 {t.get('evidence_count')}건" + (f" · {t['status']}" if t.get("status") else "") + (f" · 오류 {t['error']}" if t.get("error") else "")
        else:
            detail = "최종 메모 작성" + ("" if t.get("parsed") else " (JSON 파싱 실패)")
        lines.append(f"| {t['step']} | {t['actor']} | {t['action']} | {detail} |")
    lines.append("")
    return "\n".join(lines)
