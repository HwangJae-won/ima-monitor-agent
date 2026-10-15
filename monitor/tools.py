"""조사 Agent 가 호출하는 도구 4종.

공통 규칙
- 모든 도구는 기준일 asof(YYYYMMDD) 를 받고, 그 날짜 이전에 공개된 자료만 반환한다.
  DART 는 접수일(rcept_dt), KIS 는 영업일자 기준. 사례 복기의 정직성은 여기서 나온다.
- 숫자 계산은 전부 여기(코드)에서 한다. LLM 은 계산하지 않고 인용만 한다.
- 반환값의 evidence 항목마다 고유 id 를 붙인다. 메모는 이 id 로만 근거를 댈 수 있고,
  verify.py 가 메모의 숫자·id 가 실제 evidence 에 있는지 검사한다.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from typing import Any

from .config import shift
from .dart_client import DARTClient
from .kis_client import KISClient, business_days_back

DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

# ── 계정 과목 동의어 (account_nm 정규화 후 완전 일치) ────────────────────
_ACCOUNTS: dict[str, tuple[str, list[str]]] = {
    # key: (재무제표 구분, 동의어)
    "revenue": ("IS", ["매출액", "수익(매출액)", "영업수익", "매출", "매출및지분법손익"]),
    "operating_income": ("IS", ["영업이익", "영업이익(손실)", "영업손실"]),
    "net_income": ("IS", ["당기순이익", "당기순이익(손실)", "당기순손실", "분기순이익", "분기순이익(손실)",
                           "반기순이익", "반기순이익(손실)", "분기순손실", "반기순손실"]),
    "interest_expense": ("IS", ["이자비용", "금융비용", "금융원가"]),
    "ocf": ("CF", ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로부터의현금흐름", "영업활동순현금흐름"]),
    "cash": ("BS", ["현금및현금성자산"]),
    "short_borrowings": ("BS", ["단기차입금"]),
    "current_ltd": ("BS", ["유동성장기부채", "유동성장기차입금", "유동성사채", "유동성장기차입금및사채", "유동성장기부채(순액)"]),
    "long_borrowings": ("BS", ["장기차입금"]),
    "bonds": ("BS", ["사채", "회사채", "전환사채", "사채(순액)"]),
    "current_assets": ("BS", ["유동자산"]),
    "current_liabilities": ("BS", ["유동부채"]),
    "total_liabilities": ("BS", ["부채총계"]),
    "total_equity": ("BS", ["자본총계"]),
    "total_assets": ("BS", ["자산총계"]),
}

_KEYWORDS = {
    "funding": ["유상증자", "전환사채", "신주인수권", "교환사채", "증권신고서", "증권발행실적", "회사채", "기업어음",
                "차입", "자금조달", "일괄신고", "채무증권"],
    "credit_event": ["회생", "부도", "채권은행", "영업정지", "파산", "워크아웃", "채무불이행", "기한이익상실", "관리절차"],
    "audit": ["감사보고서", "감사의견", "의견거절", "한정", "계속기업"],
    "legal": ["소송", "가처분", "제재"],
    "governance": ["최대주주", "대표이사", "경영권", "횡령", "배임"],
    "periodic": ["사업보고서", "분기보고서", "반기보고서"],
    "correction": ["기재정정", "정정"],
}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-\_·,.'\"]", "", s or "")


def _amt(v) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _pct(cur, prev) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def _r(x, n=1):
    return None if x is None else round(x, n)


class Toolbox:
    def __init__(self, kis: KISClient, dart: DARTClient):
        self.kis = kis
        self.dart = dart
        self.evidence: dict[str, dict] = {}

    def _add(self, ev: dict) -> str:
        self.evidence[ev["id"]] = ev
        return ev["id"]

    # ── 1. 재무 스냅샷 ─────────────────────────────────────────────────
    def get_financial_snapshot(self, stock_code: str, asof: str) -> dict:
        corp = self.dart.corp_by_stock(stock_code)
        rows, meta = self.dart.latest_report_before(corp["corp_code"], asof)
        if not rows:
            return {"asof": asof, "error": f"{asof} 이전에 접수된 정기보고서 재무제표를 DART 에서 찾지 못함", "evidence": []}

        picked: dict[str, dict] = {}
        for key, (sj, names) in _ACCOUNTS.items():
            for r in rows:
                if r.get("sj_div") != sj:
                    continue
                if _norm(r.get("account_nm", "")) in [_norm(n) for n in names]:
                    cur_add, prev_add = _amt(r.get("thstrm_add_amount")), _amt(r.get("frmtrm_add_amount"))
                    use_cum = sj in ("IS", "CF") and cur_add is not None
                    picked[key] = {
                        "account_nm": r.get("account_nm"),
                        "current": cur_add if use_cum else _amt(r.get("thstrm_amount")),
                        "prior": prev_add if use_cum else _amt(r.get("frmtrm_amount")),
                        "basis": "누적" if use_cum else "당기",
                        "current_label": r.get("thstrm_nm"),
                        "prior_label": r.get("frmtrm_nm"),
                    }
                    break

        def cur(k):
            return picked.get(k, {}).get("current")

        def prev(k):
            return picked.get(k, {}).get("prior")

        def sum_(keys, fn):
            vals = [fn(k) for k in keys if fn(k) is not None]
            return sum(vals) if vals else None

        debt_keys = ["short_borrowings", "current_ltd", "long_borrowings", "bonds"]
        total_debt, total_debt_prev = sum_(debt_keys, cur), sum_(debt_keys, prev)
        short_debt, short_debt_prev = sum_(["short_borrowings", "current_ltd"], cur), sum_(["short_borrowings", "current_ltd"], prev)
        interest = cur("interest_expense")
        op = cur("operating_income")

        metrics = {
            "interest_coverage": _r(op / interest, 2) if (op is not None and interest and interest > 0) else None,
            "interest_coverage_note": (
                "이자비용 계정을 찾지 못함(주석 확인 필요)" if interest is None
                else f"분모={picked['interest_expense']['account_nm']}"
            ),
            "net_debt": (total_debt - cur("cash")) if (total_debt is not None and cur("cash") is not None) else None,
            "total_debt": total_debt,
            "total_debt_change_pct": _pct(total_debt, total_debt_prev),
            "short_term_debt": short_debt,
            "short_term_debt_change_pct": _pct(short_debt, short_debt_prev),
            "short_term_debt_share_pct": _r(short_debt / total_debt * 100) if (short_debt and total_debt) else None,
            "cash": cur("cash"),
            "cash_change_pct": _pct(cur("cash"), prev("cash")),
            "ocf": cur("ocf"),
            "ocf_change_pct": _pct(cur("ocf"), prev("ocf")),
            "operating_income": op,
            "operating_income_change_pct": _pct(op, prev("operating_income")),
            "revenue_change_pct": _pct(cur("revenue"), prev("revenue")),
            "current_ratio_pct": _r(cur("current_assets") / cur("current_liabilities") * 100)
            if (cur("current_assets") and cur("current_liabilities")) else None,
            "debt_to_equity_pct": _r(cur("total_liabilities") / cur("total_equity") * 100)
            if (cur("total_liabilities") and cur("total_equity") and cur("total_equity") > 0) else None,
            "capital_impairment": bool(cur("total_equity") is not None and cur("total_equity") <= 0),
            "cash_to_short_debt_pct": _r(cur("cash") / short_debt * 100) if (cur("cash") is not None and short_debt) else None,
        }
        missing = [k for k in _ACCOUNTS if k not in picked]

        ev_id = self._add(
            {
                "id": f"E-D-{meta['rcept_no']}-FS",
                "source": "DART",
                "date": meta["rcept_dt"],
                "title": f"{corp['corp_name']} {meta['bsns_year']} {meta['reprt_name']} 재무제표({meta['fs_div']})",
                "url": DART_VIEW + str(meta["rcept_no"]),
                "data": {"accounts": picked, "metrics": metrics, "period": {"current": meta["thstrm_nm"], "prior": meta["frmtrm_nm"]}},
            }
        )

        # KIS 재무비율로 교차검증 (결산년월 <= 기준월만)
        cross = {}
        try:
            stab = [r for r in self.kis.finance(stock_code, "stability", quarterly=True) if r.get("stac_yymm", "") <= asof[:6]]
            if stab:
                s = stab[0]
                cross = {"stac_yymm": s.get("stac_yymm"), "debt_ratio_pct": _amt(s.get("lblt_rate")),
                         "borrowing_dependency_pct": _amt(s.get("bram_depn")), "current_ratio_pct": _amt(s.get("crnt_rate"))}
                self._add({"id": f"E-K-FIN-{stock_code}-{s.get('stac_yymm')}", "source": "KIS", "date": s.get("stac_yymm", "") + "00",
                           "title": f"KIS 안정성비율 (결산 {s.get('stac_yymm')})", "data": cross})
        except Exception as e:  # 교차검증은 보조이므로 실패해도 진행
            cross = {"error": str(e)}

        return {
            "asof": asof,
            "company": corp["corp_name"],
            "report": {k: meta[k] for k in ("rcept_dt", "bsns_year", "reprt_name", "fs_div")},
            "data_public_since": meta["rcept_dt"],
            "metrics": metrics,
            "accounts": {k: {"name": v["account_nm"], "current": v["current"], "prior": v["prior"], "basis": v["basis"]} for k, v in picked.items()},
            "missing_accounts": missing,
            "kis_cross_check": cross,
            "evidence": [ev_id] + [k for k in self.evidence if k.startswith(f"E-K-FIN-{stock_code}")],
        }

    # ── 2. 공시 조회 ───────────────────────────────────────────────────
    def get_disclosures(self, stock_code: str, asof: str, lookback_days: int = 180, category: str | None = None) -> dict:
        corp = self.dart.corp_by_stock(stock_code)
        bgn = shift(asof, -lookback_days)
        filings = [f for f in self.dart.filings(corp["corp_code"], bgn, asof) if f["rcept_dt"] <= asof]
        events = [e for e in self.dart.major_events(corp["corp_code"], bgn, asof) if e.get("rcept_dt", "") and e["rcept_dt"] <= asof]
        bonds = [b for b in self.dart.bond_registrations(corp["corp_code"], bgn, asof) if b["rcept_dt"] <= asof]

        items = []
        for f in filings:
            cat = _categorize(f.get("report_nm", ""))
            if category and cat != category:
                continue
            ev_id = self._add({"id": f"E-D-{f['rcept_no']}", "source": "DART", "date": f["rcept_dt"],
                               "title": f.get("report_nm"), "url": DART_VIEW + f["rcept_no"],
                               "data": {"filer": f.get("flr_nm"), "remark": f.get("rm"), "category": cat}})
            items.append({"evidence": ev_id, "date": f["rcept_dt"], "title": f.get("report_nm"), "category": cat})

        structured = []
        for e in events + bonds:
            if "error" in e:
                continue
            if category and e["category"] != category:
                continue
            compact = {k: v for k, v in e.items() if k not in ("corp_code", "corp_cls", "corp_name") and v not in ("", "-", None)}
            ev_id = self._add({"id": f"E-D-{e['rcept_no']}-{_slug(e['event_type'])}", "source": "DART", "date": e["rcept_dt"],
                               "title": e["event_type"], "url": DART_VIEW + e["rcept_no"], "data": compact})
            structured.append({"evidence": ev_id, "date": e["rcept_dt"], "event_type": e["event_type"],
                               "category": e["category"], "key_fields": _key_fields(compact)})

        counts: dict[str, int] = {}
        for it in items:
            counts[it["category"]] = counts.get(it["category"], 0) + 1
        important = [it for it in items if it["category"] != "other"]
        return {
            "asof": asof,
            "window": [bgn, asof],
            "company": corp["corp_name"],
            "filing_counts_by_category": counts,
            "filings": important[-40:] + [it for it in items if it["category"] == "other"][-10:],
            "structured_events": structured,
            "evidence": [it["evidence"] for it in items] + [s["evidence"] for s in structured],
        }

    # ── 3. 시장 신호 ───────────────────────────────────────────────────
    def get_market_signals(self, stock_code: str, asof: str, lookback_days: int = 120) -> dict:
        start = shift(asof, -int(lookback_days * 1.6))
        prices = self.kis.daily_prices(stock_code, start, asof)
        out: dict[str, Any] = {"asof": asof, "evidence": []}
        if len(prices) < 25:
            out["error"] = f"{asof} 이전 일봉이 {len(prices)}건뿐 (상장폐지·거래정지·신규상장 가능성)"
            return out

        closes = [p["close"] for p in prices if p["close"]]
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1]]
        last = closes[-1]

        def ret(n):
            return _r((last / closes[-1 - n] - 1) * 100) if len(closes) > n else None

        vol20 = _r(statistics.pstdev(rets[-20:]) * math.sqrt(252) * 100) if len(rets) >= 20 else None
        window = closes[-60:]
        peak, mdd = window[0], 0.0
        for c in window:
            peak = max(peak, c)
            mdd = min(mdd, (c / peak - 1) * 100)
        vols = [p["volume"] or 0 for p in prices]
        vol_ratio = _r(statistics.mean(vols[-5:]) / statistics.mean(vols[-65:-5]), 2) if len(vols) >= 65 and statistics.mean(vols[-65:-5]) else None
        price_stats = {"last_date": prices[-1]["date"], "last_close": last, "return_20d_pct": ret(20), "return_60d_pct": ret(60),
                       "volatility_20d_annualized_pct": vol20, "max_drawdown_60d_pct": _r(mdd), "volume_ratio_5d_vs_60d": vol_ratio,
                       "n_days": len(prices)}
        out["price"] = price_stats
        out["evidence"].append(self._add({"id": f"E-K-PRICE-{stock_code}-{asof}", "source": "KIS", "date": prices[-1]["date"],
                                          "title": "KIS 일봉 기반 가격 통계", "data": price_stats}))

        try:
            credit = self.kis.credit_balance(stock_code, asof)
            if credit:
                c_last = credit[-1]
                c_prev = credit[-21] if len(credit) > 20 else credit[0]
                cs = {"last_date": c_last["date"], "loan_balance_ratio_pct": c_last["loan_balance_ratio"],
                      "loan_balance_ratio_20d_ago_pct": c_prev["loan_balance_ratio"],
                      "loan_balance_shares_change_20d_pct": _pct(c_last["loan_balance_shares"], c_prev["loan_balance_shares"])}
                out["credit_balance"] = cs
                out["evidence"].append(self._add({"id": f"E-K-CREDIT-{stock_code}-{asof}", "source": "KIS", "date": c_last["date"],
                                                  "title": "KIS 신용잔고 일별추이", "data": cs}))
        except Exception as e:
            out["credit_balance"] = {"error": str(e)}

        try:
            short = self.kis.short_sale(stock_code, business_days_back(asof, 45), asof)
            if len(short) >= 10:
                recent = [s["short_vol_ratio"] or 0 for s in short[-20:]]
                prior = [s["short_vol_ratio"] or 0 for s in short[-40:-20]] or recent
                ss = {"last_date": short[-1]["date"], "short_vol_ratio_avg_20d_pct": _r(statistics.mean(recent), 2),
                      "short_vol_ratio_avg_prior_20d_pct": _r(statistics.mean(prior), 2), "n_days": len(short)}
                out["short_sale"] = ss
                out["evidence"].append(self._add({"id": f"E-K-SHORT-{stock_code}-{asof}", "source": "KIS", "date": short[-1]["date"],
                                                  "title": "KIS 공매도 일별추이", "data": ss}))
        except Exception as e:
            out["short_sale"] = {"error": str(e)}

        try:
            inv = self.kis.investor_daily(stock_code, asof)
            if inv:
                recent = inv[-20:]
                iv = {"last_date": recent[-1]["date"], "n_days": len(recent),
                      "foreign_net_value_20d": sum(r["foreign_net_value"] or 0 for r in recent),
                      "institution_net_value_20d": sum(r["institution_net_value"] or 0 for r in recent),
                      "foreign_net_sell_days_20d": sum(1 for r in recent if (r["foreign_net_qty"] or 0) < 0),
                      "institution_net_sell_days_20d": sum(1 for r in recent if (r["institution_net_qty"] or 0) < 0)}
                out["investors"] = iv
                out["evidence"].append(self._add({"id": f"E-K-INVESTOR-{stock_code}-{asof}", "source": "KIS", "date": recent[-1]["date"],
                                                  "title": "KIS 종목별 투자자매매동향(일별)", "data": iv}))
        except Exception as e:
            out["investors"] = {"error": str(e)}

        out["note"] = "시장 신호는 투자자들의 '반응'이지 상환능력 그 자체가 아니다. 상환능력 판단은 재무·공시 근거로 한다."
        return out

    # ── 4. 자금조달 '결정' vs '완료' 확인 ──────────────────────────────
    def check_funding_completion(self, stock_code: str, asof: str, since: str) -> dict:
        corp = self.dart.corp_by_stock(stock_code)
        filings = [f for f in self.dart.filings(corp["corp_code"], since, asof) if f["rcept_dt"] <= asof]
        decisions, completions, corrections = [], [], []
        for f in filings:
            nm = f.get("report_nm", "")
            ev_id = self._add({"id": f"E-D-{f['rcept_no']}", "source": "DART", "date": f["rcept_dt"], "title": nm,
                               "url": DART_VIEW + f["rcept_no"], "data": {"filer": f.get("flr_nm"), "remark": f.get("rm")}})
            entry = {"evidence": ev_id, "date": f["rcept_dt"], "title": nm}
            if any(k in nm for k in ("발행결정", "유상증자결정", "증권신고서", "일괄신고추가서류", "차입결정")):
                decisions.append(entry)
            elif any(k in nm for k in ("증권발행실적보고서", "발행조건확정", "납입", "증자등기", "발행완료")):
                completions.append(entry)
            elif "정정" in nm or "철회" in nm:
                corrections.append(entry)
        if decisions:
            if completions and max(c["date"] for c in completions) >= min(d["date"] for d in decisions):
                status = "조달 완료 공시 확인"
            elif corrections:
                status = "결정 이후 정정·철회 공시 있음 — 원문 확인 필요"
            else:
                status = "계획(결정) 공시만 확인 — 조달 완료 공시 미확인"
        else:
            status = "조회 기간 내 자금조달 결정 공시 없음"
        return {"asof": asof, "window": [since, asof], "status": status, "decisions": decisions,
                "completions": completions, "corrections": corrections,
                "evidence": [d["evidence"] for d in decisions + completions + corrections],
                "note": "발행 '결정'은 계획이다. 실제 납입·실적 공시가 있어야 조달 완료로 본다."}


def _categorize(name: str) -> str:
    for cat in ("credit_event", "audit", "funding", "legal", "governance", "correction", "periodic"):
        if any(k in name for k in _KEYWORDS[cat]):
            return cat
    return "other"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9가-힣]", "", s)[:12]


def _key_fields(d: dict) -> dict:
    keys = [k for k in d if any(t in k for t in ("amt", "amount", "bd_tm", "bd_knd", "fdpp", "pymd", "rsn", "ctr_", "rcept_dt", "lwst", "bnk", "nstk_"))]
    return {k: d[k] for k in keys[:14]}


# ── OpenAI function-calling 스펙 ──────────────────────────────────────
TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_disclosures",
            "description": "기준일 이전 N일 동안 DART 에 접수된 공시 목록과 주요사항보고서(자금조달·신용사건·소송 등)를 조회한다. "
                           "category 로 funding/credit_event/audit/legal/governance 만 골라 볼 수 있다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer", "description": "기준일로부터 며칠 전까지 볼지 (기본 180)"},
                    "category": {"type": "string", "enum": ["funding", "credit_event", "audit", "legal", "governance", "periodic"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_funding_completion",
            "description": "since 이후의 자금조달 '결정' 공시가 실제 '완료'(발행실적·납입) 공시로 이어졌는지 확인한다. "
                           "차환·증자 계획을 조달 완료로 오해하지 않기 위해 반드시 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {"since": {"type": "string", "description": "조회 시작일 YYYYMMDD"}},
                "required": ["since"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_snapshot",
            "description": "다른 기준일(과거) 시점에 공개돼 있던 최신 정기보고서 재무 스냅샷을 가져와 현재와 비교할 때 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {"asof": {"type": "string", "description": "과거 기준일 YYYYMMDD"}},
                "required": ["asof"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_signals",
            "description": "KIS API 로 주가·변동성·거래량·신용잔고·공매도·투자자 매매동향을 다른 기간으로 다시 본다.",
            "parameters": {
                "type": "object",
                "properties": {"lookback_days": {"type": "integer", "description": "며칠 치 시세를 볼지 (기본 120)"}},
            },
        },
    },
]


def compact_for_llm(result: dict, max_chars: int = 6000) -> str:
    """도구 결과를 LLM 에 넘길 때 토큰을 아끼기 위해 길이를 제한한다. evidence id 는 항상 보존."""
    s = json.dumps(result, ensure_ascii=False, default=str)
    if len(s) <= max_chars:
        return s
    trimmed = dict(result)
    for k in ("filings", "structured_events", "decisions", "completions"):
        if isinstance(trimmed.get(k), list):
            trimmed[k] = trimmed[k][-15:]
    s = json.dumps(trimmed, ensure_ascii=False, default=str)
    return s[:max_chars] + ("…(truncated)" if len(s) > max_chars else "")
