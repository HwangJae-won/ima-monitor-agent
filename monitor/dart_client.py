"""OpenDART 클라이언트.

기준일(as-of) 처리의 핵심은 접수번호(rcept_no) 앞 8자리 = 접수일(YYYYMMDD) 이라는 점이다.
모든 결과에 rcept_dt 를 붙여 두고, 도구 계층에서 rcept_dt <= asof 로 걸러낸다.
그래야 "그 시점에 공개돼 있던 자료만으로" 복기할 수 있다.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import requests

from . import cache
from .config import require

BASE = "https://opendart.fss.or.kr/api"

# 보고서 코드: 1분기 11013, 반기 11012, 3분기 11014, 사업보고서 11011
REPORT_CODES = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업보고서"}

# 주요사항보고서 주요정보 API 중 상환능력·자금조달과 관련된 것만.
# (엔드포인트, 사건 유형, 카테고리)
MAJOR_EVENT_APIS = [
    ("ctrcvsBgrq", "회생절차 개시신청", "credit_event"),
    ("dfOcr", "부도발생", "credit_event"),
    ("bnkMngtPcbg", "채권은행 등의 관리절차 개시", "credit_event"),
    ("bsnSp", "영업정지", "credit_event"),
    ("dsRsOcr", "해산사유 발생", "credit_event"),
    ("piicDecsn", "유상증자 결정", "funding"),
    ("cvbdIsDecsn", "전환사채권 발행결정", "funding"),
    ("bdwtIsDecsn", "신주인수권부사채권 발행결정", "funding"),
    ("exbdIsDecsn", "교환사채권 발행결정", "funding"),
    ("crDecsn", "감자 결정", "capital"),
    ("lwstLg", "소송 등의 제기", "legal"),
    ("tgastTrfDecsn", "유형자산 양도결정", "asset_sale"),
    ("bsnTrfDecsn", "영업양도 결정", "asset_sale"),
    ("otcprStkInvscrTrfDecsn", "타법인 주식 양도결정", "asset_sale"),
]


class DARTError(RuntimeError):
    pass


class DARTClient:
    def __init__(self, api_key: str | None = None):
        self.key = api_key or require("DART_API_KEY")

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        ns = f"dart_{endpoint}"
        cached = cache.get(ns, params)
        if cached is not None:
            return cached
        r = requests.get(f"{BASE}/{endpoint}.json", params={**params, "crtfc_key": self.key}, timeout=30)
        body = r.json()
        status = body.get("status")
        if status not in ("000", "013"):  # 013 = 조회 결과 없음
            raise DARTError(f"{endpoint}: {status} {body.get('message')}")
        cache.put(ns, params, body)
        return body

    # ── 고유번호 ─────────────────────────────────────────────────────────
    def corp_codes(self) -> list[dict]:
        f = cache.cache_path("dart_corp_codes.json")
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": self.key}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read(z.namelist()[0])
        root = ET.fromstring(xml)
        rows = []
        for el in root.iter("list"):
            stock = (el.findtext("stock_code") or "").strip()
            if not stock:
                continue  # 상장사만
            rows.append(
                {
                    "corp_code": el.findtext("corp_code"),
                    "corp_name": el.findtext("corp_name"),
                    "stock_code": stock,
                    "modify_date": el.findtext("modify_date"),
                }
            )
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows

    def corp_by_stock(self, stock_code: str) -> dict:
        for r in self.corp_codes():
            if r["stock_code"] == stock_code:
                return r
        raise DARTError(f"상장 종목코드 {stock_code} 에 해당하는 DART 고유번호가 없습니다")

    # ── 공시 목록 ────────────────────────────────────────────────────────
    def filings(self, corp_code: str, bgn: str, end: str) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while page <= 10:
            body = self._get(
                "list",
                {"corp_code": corp_code, "bgn_de": bgn, "end_de": end, "page_no": page, "page_count": 100},
            )
            items = body.get("list", []) or []
            rows.extend(items)
            if page >= int(body.get("total_page", 1) or 1):
                break
            page += 1
        for r in rows:
            r["rcept_dt"] = r.get("rcept_dt") or r.get("rcept_no", "")[:8]
        return sorted(rows, key=lambda r: r["rcept_dt"])

    # ── 재무제표 (단일회사 전체) ─────────────────────────────────────────
    def financials(self, corp_code: str, year: int, reprt_code: str) -> list[dict]:
        """연결(CFS) 우선, 없으면 개별(OFS). 각 행에 rcept_dt 를 붙인다."""
        for fs_div in ("CFS", "OFS"):
            body = self._get(
                "fnlttSinglAcntAll",
                {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code, "fs_div": fs_div},
            )
            items = body.get("list", []) or []
            if items:
                for r in items:
                    r["rcept_dt"] = r.get("rcept_no", "")[:8]
                    r["fs_div"] = fs_div
                    r["reprt_name"] = REPORT_CODES.get(reprt_code, reprt_code)
                return items
        return []

    # ── 주요사항보고서 주요정보 ──────────────────────────────────────────
    def major_events(self, corp_code: str, bgn: str, end: str) -> list[dict]:
        out = []
        for endpoint, label, category in MAJOR_EVENT_APIS:
            try:
                body = self._get(endpoint, {"corp_code": corp_code, "bgn_de": bgn, "end_de": end})
            except DARTError as e:
                out.append({"event_type": label, "category": category, "error": str(e)})
                continue
            for r in body.get("list", []) or []:
                r = dict(r)
                r["event_type"] = label
                r["category"] = category
                r["rcept_dt"] = r.get("rcept_no", "")[:8]
                out.append(r)
        return sorted(out, key=lambda r: r.get("rcept_dt", ""))

    def bond_registrations(self, corp_code: str, bgn: str, end: str) -> list[dict]:
        """증권신고서(채무증권) 주요정보 — 회사채 발행 '계획' 단계의 공개 자료."""
        body = self._get("bdRs", {"corp_code": corp_code, "bgn_de": bgn, "end_de": end})
        rows = []
        for r in body.get("list", []) or []:
            r = dict(r)
            r["event_type"] = "증권신고서(채무증권)"
            r["category"] = "funding"
            r["rcept_dt"] = r.get("rcept_no", "")[:8]
            rows.append(r)
        return sorted(rows, key=lambda r: r["rcept_dt"])

    def latest_report_before(self, corp_code: str, asof: str) -> tuple[list[dict], dict] | tuple[list, dict]:
        """asof 이전에 접수된 가장 최근 정기보고서의 재무제표와 메타."""
        year = int(asof[:4])
        candidates: list[tuple[str, list[dict]]] = []
        for y in (year, year - 1):
            for code in ("11011", "11014", "11012", "11013"):
                rows = self.financials(corp_code, y, code)
                rows = [r for r in rows if r["rcept_dt"] and r["rcept_dt"] <= asof]
                if rows:
                    candidates.append((rows[0]["rcept_dt"], rows))
        if not candidates:
            return [], {}
        candidates.sort(key=lambda c: c[0], reverse=True)
        rows = candidates[0][1]
        meta = {
            "rcept_no": rows[0].get("rcept_no"),
            "rcept_dt": rows[0]["rcept_dt"],
            "bsns_year": rows[0].get("bsns_year"),
            "reprt_name": rows[0].get("reprt_name"),
            "fs_div": rows[0].get("fs_div"),
            "thstrm_nm": rows[0].get("thstrm_nm"),
            "frmtrm_nm": rows[0].get("frmtrm_nm"),
        }
        return rows, meta
