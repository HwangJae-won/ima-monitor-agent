"""네트워크 없이 도구를 검사하기 위한 가짜 KIS·DART 클라이언트."""

from __future__ import annotations

import pytest

from monitor.tools import Toolbox


def _fs_row(sj, name, cur, prev, rcept_no, cum=None, cum_prev=None):
    return {"sj_div": sj, "account_nm": name, "thstrm_amount": str(cur), "frmtrm_amount": str(prev),
            "thstrm_add_amount": "" if cum is None else str(cum), "frmtrm_add_amount": "" if cum_prev is None else str(cum_prev),
            "rcept_no": rcept_no, "rcept_dt": rcept_no[:8], "bsns_year": "2025", "reprt_name": "반기",
            "fs_div": "CFS", "thstrm_nm": "제 10 기 반기", "frmtrm_nm": "제 9 기"}


class FakeDART:
    def __init__(self):
        # 2025.08.14 접수 반기보고서, 2025.03.20 접수 사업보고서
        self.reports = {
            "20250814000001": [
                _fs_row("IS", "매출액", 1000, 1200, "20250814000001"),
                _fs_row("IS", "영업이익", 50, 120, "20250814000001"),
                _fs_row("IS", "이자비용", 60, 40, "20250814000001"),
                _fs_row("CF", "영업활동현금흐름", -80, 150, "20250814000001"),
                _fs_row("BS", "현금및현금성자산", 100, 300, "20250814000001"),
                _fs_row("BS", "단기차입금", 400, 250, "20250814000001"),
                _fs_row("BS", "유동성장기부채", 100, 100, "20250814000001"),
                _fs_row("BS", "장기차입금", 300, 350, "20250814000001"),
                _fs_row("BS", "유동자산", 500, 700, "20250814000001"),
                _fs_row("BS", "유동부채", 800, 600, "20250814000001"),
                _fs_row("BS", "부채총계", 1500, 1300, "20250814000001"),
                _fs_row("BS", "자본총계", 400, 600, "20250814000001"),
                _fs_row("BS", "자산총계", 1900, 1900, "20250814000001"),
            ],
            "20250320000001": [
                _fs_row("IS", "매출액", 2400, 2200, "20250320000001"),
                _fs_row("IS", "영업이익", 240, 200, "20250320000001"),
                _fs_row("IS", "이자비용", 80, 70, "20250320000001"),
                _fs_row("CF", "영업활동현금흐름", 300, 250, "20250320000001"),
                _fs_row("BS", "현금및현금성자산", 300, 280, "20250320000001"),
                _fs_row("BS", "단기차입금", 250, 240, "20250320000001"),
                _fs_row("BS", "부채총계", 1300, 1250, "20250320000001"),
                _fs_row("BS", "자본총계", 600, 580, "20250320000001"),
            ],
        }
        self._filings = [
            {"rcept_no": "20250610000010", "rcept_dt": "20250610", "report_nm": "주요사항보고서(전환사채권발행결정)", "flr_nm": "테스트", "rm": ""},
            {"rcept_no": "20250702000011", "rcept_dt": "20250702", "report_nm": "증권발행실적보고서", "flr_nm": "테스트", "rm": ""},
            {"rcept_no": "20250814000001", "rcept_dt": "20250814", "report_nm": "반기보고서 (2025.06)", "flr_nm": "테스트", "rm": ""},
            {"rcept_no": "20250905000012", "rcept_dt": "20250905", "report_nm": "주요사항보고서(회생절차개시신청)", "flr_nm": "테스트", "rm": ""},
        ]

    def corp_by_stock(self, stock_code):
        return {"corp_code": "00000001", "corp_name": "테스트기업", "stock_code": stock_code}

    def latest_report_before(self, corp_code, asof):
        cands = [(no, rows) for no, rows in self.reports.items() if no[:8] <= asof]
        if not cands:
            return [], {}
        no, rows = max(cands, key=lambda c: c[0])
        return rows, {"rcept_no": no, "rcept_dt": no[:8], "bsns_year": "2025", "reprt_name": rows[0]["reprt_name"],
                      "fs_div": "CFS", "thstrm_nm": rows[0]["thstrm_nm"], "frmtrm_nm": rows[0]["frmtrm_nm"]}

    def filings(self, corp_code, bgn, end):
        return [f for f in self._filings if bgn <= f["rcept_dt"] <= end]

    def major_events(self, corp_code, bgn, end):
        return [{"rcept_no": "20250610000010", "rcept_dt": "20250610", "event_type": "전환사채권 발행결정", "category": "funding",
                 "bd_tm": "5", "bd_knd": "무기명식 이권부 무보증 사모 전환사채", "bd_fta": "10,000,000,000", "fdpp_fclt": "운영자금"}] \
            if bgn <= "20250610" <= end else []

    def bond_registrations(self, corp_code, bgn, end):
        return []


class FakeKIS:
    def __init__(self):
        from datetime import date, timedelta
        d, rows, px = date(2025, 1, 2), [], 10000.0
        while d <= date(2025, 10, 15):
            if d.weekday() < 5:
                px *= 0.985 if d >= date(2025, 8, 20) else 1.0005  # 8월 20일부터 꾸준히 하락
                rows.append({"date": d.strftime("%Y%m%d"), "close": round(px), "open": px, "high": px, "low": px,
                             "volume": 100000 if d < date(2025, 9, 1) else 400000, "value": 1.0, "adj_flag": ""})
            d += timedelta(days=1)
        self._prices = rows

    def finance(self, code, kind, quarterly=False):
        return [{"stac_yymm": "202506", "lblt_rate": "375.0", "bram_depn": "42.1", "crnt_rate": "62.5"}]

    def daily_prices(self, code, start, end):
        return [r for r in self._prices if start <= r["date"] <= end]

    def credit_balance(self, code, asof, pages=2):
        rows = [r for r in self._prices if r["date"] <= asof][-60:]
        return [{"date": r["date"], "settle_date": r["date"], "loan_balance_shares": 1000 + i * 30, "loan_balance_amt": 1.0,
                 "loan_balance_ratio": 1.0 + i * 0.05, "loan_new_shares": 0, "loan_repaid_shares": 0, "stock_lending_balance_shares": 0}
                for i, r in enumerate(rows)]

    def short_sale(self, code, start, end):
        return [{"date": r["date"], "close": r["close"], "short_qty": 1, "short_vol_ratio": 2.0 if r["date"] < "20250901" else 9.0, "short_value_ratio": 1.0}
                for r in self._prices if start <= r["date"] <= end]

    def investor_daily(self, code, asof):
        rows = [r for r in self._prices if r["date"] <= asof][-30:]
        return [{"date": r["date"], "close": r["close"], "foreign_net_qty": -10, "institution_net_qty": -5, "individual_net_qty": 15,
                 "foreign_net_value": -1e6, "institution_net_value": -5e5} for r in rows]


@pytest.fixture
def toolbox(tmp_path, monkeypatch):
    import monitor.cache as cache_mod
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path / "cache")
    return Toolbox(FakeKIS(), FakeDART())
