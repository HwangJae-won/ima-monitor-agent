"""한국투자증권 KIS Developers Open API 클라이언트 — 조회 전용.

이 모듈에는 주문·정정·취소 API 가 없다. 모니터링 업무에 필요한 시세·수급·재무 조회만 둔다.
TR ID 와 파라미터는 공식 샘플 저장소(koreainvestment/open-trading-api, examples_llm/domestic_stock)를 기준으로 했다.

호출 제한 대응
- 접근토큰: 1일 유효, 발급은 1분 1회 제한 → 디스크에 캐시하고 만료 5분 전까지 재사용
- 초당 호출: 실전 20건, 모의 2건 → 호출 사이 sleep (config.KIS_SLEEP)
- EGW00201(초당 초과) 는 지수 백오프로 최대 3회 재시도
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from . import cache
from .config import KIS_BASE, KIS_SLEEP, env, parse_ymd, require, shift, ymd


class KISError(RuntimeError):
    pass


class KISClient:
    def __init__(self, appkey: str | None = None, appsecret: str | None = None, kis_env: str | None = None):
        # KIS_AUTH_MODE=proxy: 키·토큰을 코드가 전혀 다루지 않는다. 세션의 네트워크 시크릿(프록시)이
        # openapi.koreainvestment.com 으로 나가는 요청에 authorization/appkey/appsecret 헤더를 붙인다.
        # 토큰은 사용자가 PC 에서 발급해 시크릿에 넣는다(1일 유효). 기본(env) 모드는 .env 의 키로 직접 발급한다.
        self.auth_mode = env("KIS_AUTH_MODE", "env")
        if self.auth_mode == "proxy":
            self.appkey = self.appsecret = None
        else:
            self.appkey = appkey or require("KIS_APP_KEY")
            self.appsecret = appsecret or require("KIS_APP_SECRET")
        self.kis_env = kis_env or env("KIS_ENV", "prod")
        self.base = KIS_BASE[self.kis_env]
        self.sleep = KIS_SLEEP[self.kis_env]
        self._token: str | None = None
        self._token_exp: datetime | None = None
        self._last_call = 0.0

    # ── 인증 ────────────────────────────────────────────────────────────
    def _token_file(self):
        # 파일명에서 토큰값을 유추할 수 없게 고정 이름 사용 (샘플 README 권고)
        return cache.cache_path(f"kis_token_{self.kis_env}.json")

    def token(self) -> str:
        now = datetime.now()
        if self._token and self._token_exp and self._token_exp - now > timedelta(minutes=5):
            return self._token
        f = self._token_file()
        if f.exists():
            saved = json.loads(f.read_text())
            exp = datetime.fromisoformat(saved["expires_at"])
            if exp - now > timedelta(minutes=5):
                self._token, self._token_exp = saved["access_token"], exp
                return self._token
        r = requests.post(
            f"{self.base}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": self.appkey, "appsecret": self.appsecret},
            timeout=15,
        )
        body = r.json()
        if "access_token" not in body:
            raise KISError(f"토큰 발급 실패: {body.get('error_code')} {body.get('error_description')}")
        self._token = body["access_token"]
        self._token_exp = now + timedelta(seconds=int(body.get("expires_in", 86400)))
        f.write_text(json.dumps({"access_token": self._token, "expires_at": self._token_exp.isoformat()}))
        return self._token

    # ── 공통 GET ────────────────────────────────────────────────────────
    def _get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict:
        ns = f"kis_{tr_id}"
        cached = cache.get(ns, params)
        if cached is not None:
            return cached
        headers = {"content-type": "application/json; charset=utf-8", "tr_id": tr_id, "custtype": "P"}
        if self.auth_mode != "proxy":
            headers.update({"authorization": f"Bearer {self.token()}", "appkey": self.appkey, "appsecret": self.appsecret})
        for attempt in range(4):
            wait = self.sleep - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            r = requests.get(f"{self.base}{path}", headers=headers, params=params, timeout=20)
            try:
                body = r.json()
            except ValueError as e:
                raise KISError(f"{tr_id}: 비정상 응답 HTTP {r.status_code}") from e
            if body.get("rt_cd") == "0":
                cache.put(ns, params, body)
                return body
            code = body.get("msg_cd", "")
            if self.auth_mode == "proxy" and code in ("EGW00121", "EGW00123"):  # 토큰 오류·만료
                raise KISError(f"{tr_id}: {code} — 프록시 시크릿의 토큰이 만료됐을 수 있습니다. PC 에서 토큰을 다시 발급해 시크릿 값을 갱신하세요.")
            if code == "EGW00201" and attempt < 3:  # 초당 거래건수 초과
                time.sleep(0.5 * (2**attempt))
                continue
            raise KISError(f"{tr_id}: {code} {body.get('msg1', '')}".strip())
        raise KISError(f"{tr_id}: 재시도 초과")

    # ── 시세 ────────────────────────────────────────────────────────────
    def daily_prices(self, code: str, start: str, end: str) -> list[dict]:
        """일봉. 1회 100건 제한이라 end 를 뒤로 옮기며 start 까지 모은다. 수정주가 기준.

        FID_ORG_ADJ_PRC 는 샘플 docstring 기준 0=수정주가. 커뮤니티에 의미가 반대라는 보고가 있어
        결과의 flng_cls_code(락 구분)·mod_yn 을 함께 저장해 두고 README 에 확인 사항으로 남긴다.
        """
        rows: list[dict] = []
        cursor = end
        for _ in range(40):  # 안전장치: 최대 4,000 영업일
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "FHKST03010100",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": start,
                    "FID_INPUT_DATE_2": cursor,
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "0",
                },
            )
            chunk = [r for r in body.get("output2", []) if r.get("stck_bsop_date")]
            if not chunk:
                break
            rows.extend(chunk)
            oldest = min(r["stck_bsop_date"] for r in chunk)
            if oldest <= start or len(chunk) < 100:
                break
            cursor = shift(oldest, -1)
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: r["stck_bsop_date"]):
            d = r["stck_bsop_date"]
            if d in seen or d < start or d > end:
                continue
            seen.add(d)
            out.append(
                {
                    "date": d,
                    "close": _num(r.get("stck_clpr")),
                    "open": _num(r.get("stck_oprc")),
                    "high": _num(r.get("stck_hgpr")),
                    "low": _num(r.get("stck_lwpr")),
                    "volume": _num(r.get("acml_vol")),
                    "value": _num(r.get("acml_tr_pbmn")),
                    "adj_flag": r.get("flng_cls_code", ""),
                }
            )
        return out

    def stock_info(self, code: str) -> dict:
        """현재가 조회의 output 에서 종목명·시가총액·상장주수 등 기본 정보만 추린다."""
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        o = body.get("output", {})
        return {
            "code": code,
            "market_cap_억": _num(o.get("hts_avls")),
            "listed_shares": _num(o.get("lstn_stcn")),
            "per": _num(o.get("per")),
            "pbr": _num(o.get("pbr")),
            "credit_ratio": _num(o.get("whol_loan_rmnd_rate")),
            "margin_flag": o.get("mrkt_warn_cls_code", ""),
            "trading_halt": o.get("temp_stop_yn", ""),
        }

    # ── 수급 ────────────────────────────────────────────────────────────
    def credit_balance(self, code: str, asof: str, pages: int = 2) -> list[dict]:
        """신용잔고 일별추이. 1회 30건, 결제일 기준. asof 이전만 반환."""
        rows: list[dict] = []
        cursor = asof
        for _ in range(pages):
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/daily-credit-balance",
                "FHPST04760000",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_COND_SCR_DIV_CODE": "20476",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": cursor,
                },
            )
            chunk = body.get("output", []) or []
            if not chunk:
                break
            rows.extend(chunk)
            oldest = min(r.get("deal_date", cursor) for r in chunk)
            cursor = shift(oldest, -1)
        out = []
        for r in sorted(rows, key=lambda r: r.get("deal_date", "")):
            d = r.get("deal_date", "")
            if not d or d > asof:
                continue
            out.append(
                {
                    "date": d,
                    "settle_date": r.get("stlm_date", ""),
                    "loan_balance_shares": _num(r.get("whol_loan_rmnd_stcn")),
                    "loan_balance_amt": _num(r.get("whol_loan_rmnd_amt")),
                    "loan_balance_ratio": _num(r.get("whol_loan_rmnd_rate")),
                    "loan_new_shares": _num(r.get("whol_loan_new_stcn")),
                    "loan_repaid_shares": _num(r.get("whol_loan_rdmp_stcn")),
                    "stock_lending_balance_shares": _num(r.get("whol_stln_rmnd_stcn")),
                }
            )
        return out

    def short_sale(self, code: str, start: str, end: str) -> list[dict]:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/daily-short-sale",
            "FHPST04830000",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
            },
        )
        out = []
        for r in body.get("output2", []) or []:
            d = r.get("stck_bsop_date", "")
            if not d or d < start or d > end:
                continue
            out.append(
                {
                    "date": d,
                    "close": _num(r.get("stck_clpr")),
                    "short_qty": _num(r.get("ssts_cntg_qty")),
                    "short_vol_ratio": _num(r.get("ssts_vol_rlim")),
                    "short_value_ratio": _num(r.get("ssts_tr_pbmn_rlim")),
                }
            )
        return sorted(out, key=lambda r: r["date"])

    def investor_daily(self, code: str, asof: str) -> list[dict]:
        """종목별 투자자매매동향(일별). asof 를 기준일로 넣으면 그 이전 일자들이 내려온다."""
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
            "FHPTJ04160001",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": asof,
                "FID_ORG_ADJ_PRC": "",
                "FID_ETC_CLS_CODE": "",
            },
        )
        out = []
        for r in body.get("output2", []) or []:
            d = r.get("stck_bsop_date", "")
            if not d or d > asof:
                continue
            out.append(
                {
                    "date": d,
                    "close": _num(r.get("stck_clpr")),
                    "foreign_net_qty": _num(r.get("frgn_ntby_qty")),
                    "institution_net_qty": _num(r.get("orgn_ntby_qty")),
                    "individual_net_qty": _num(r.get("prsn_ntby_qty")),
                    "foreign_net_value": _num(r.get("frgn_ntby_tr_pbmn")),
                    "institution_net_value": _num(r.get("orgn_ntby_tr_pbmn")),
                }
            )
        return sorted(out, key=lambda r: r["date"])

    # ── 재무 (DART 교차검증용. 기준일 필터는 stac_yymm 으로만 가능) ──────────
    def finance(self, code: str, kind: str, quarterly: bool = False) -> list[dict]:
        tr = {
            "balance": ("/uapi/domestic-stock/v1/finance/balance-sheet", "FHKST66430100"),
            "income": ("/uapi/domestic-stock/v1/finance/income-statement", "FHKST66430200"),
            "ratio": ("/uapi/domestic-stock/v1/finance/financial-ratio", "FHKST66430300"),
            "stability": ("/uapi/domestic-stock/v1/finance/stability-ratio", "FHKST66430600"),
        }[kind]
        body = self._get(
            tr[0],
            tr[1],
            {
                "FID_DIV_CLS_CODE": "1" if quarterly else "0",
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": code,
            },
        )
        return body.get("output", []) or []


def _num(v) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def business_days_back(asof: str, n: int) -> str:
    """영업일 n 일 전 근사 (주말만 제외). 휴장일은 API 결과에 없으므로 자연히 걸러진다."""
    d = parse_ymd(asof)
    cnt = 0
    while cnt < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            cnt += 1
    return ymd(d)
