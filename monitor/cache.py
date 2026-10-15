"""API 응답 디스크 캐시.

같은 기준일로 재실행하거나 사례 복기를 여러 번 돌릴 때 네트워크 호출을 반복하지 않기 위한 것.
키에는 엔드포인트와 파라미터만 들어가고 앱키·토큰은 절대 포함하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import CACHE_DIR


def _key(namespace: str, params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(f"{namespace}|{raw}".encode()).hexdigest()[:20]


def get(namespace: str, params: dict[str, Any]) -> Any | None:
    path = CACHE_DIR / namespace / f"{_key(namespace, params)}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def put(namespace: str, params: dict[str, Any], value: Any) -> None:
    path = CACHE_DIR / namespace / f"{_key(namespace, params)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name
