"""환경변수·경로의 단일 기준점. 비밀값은 .env 에서만 읽고 어디에도 기록하지 않는다."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

CACHE_DIR = PROJECT_ROOT / os.getenv("CACHE_DIR", "data/cache")
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"

KIS_BASE = {
    "prod": "https://openapi.koreainvestment.com:9443",
    "vps": "https://openapivts.koreainvestment.com:29443",
}
# 샘플 코드 kis_auth.py 의 smart_sleep 값과 동일 (실전 0.05s ≈ 20건/초, 모의 0.5s)
KIS_SLEEP = {"prod": 0.06, "vps": 0.55}


def env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def require(name: str) -> str:
    v = env(name)
    if not v:
        raise RuntimeError(f"환경변수 {name} 가 비어 있습니다. .env 를 확인하세요.")
    return v


# ── 날짜 유틸 (모든 도구는 YYYYMMDD 문자열을 기준일로 받는다) ──
def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def shift(s: str, days: int) -> str:
    return ymd(parse_ymd(s) + timedelta(days=days))


def today_ymd() -> str:
    return ymd(date.today())
