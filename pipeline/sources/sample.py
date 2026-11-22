"""API 키 없이 돌려볼 수 있는 샘플 공고.

data/fixtures/bizinfo_sample.json은 기업마당 API 응답과 같은 모양이지만 내용은 지어낸 것이다.
제목에 [샘플]이 붙어 있고, 샘플 모드 빌드는 noindex + 경고 배너가 붙는다.
날짜는 오늘 기준 상대값으로 적어 두고 여기서 실제 날짜로 바꾼다.
  @D+5  → 오늘+5일 (YYYYMMDD)
  @T-2  → 오늘-2일 10:00:00 (YYYY-MM-DD HH:MM:SS)
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ..config import ROOT

FIXTURE_DIR = ROOT / "data" / "fixtures"
_TOKEN = re.compile(r"@([DT])([+-]\d+)")


def _resolve(value, today: date):
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            d = today + timedelta(days=int(m.group(2)))
            return d.strftime("%Y%m%d") if m.group(1) == "D" else d.strftime("%Y-%m-%d 10:00:00")

        return _TOKEN.sub(sub, value)
    if isinstance(value, list):
        return [_resolve(v, today) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, today) for k, v in value.items()}
    return value


def load_raw(today: date) -> list[dict]:
    data = json.loads((FIXTURE_DIR / "bizinfo_sample.json").read_text(encoding="utf-8"))
    return _resolve(data["jsonArray"], today)


def load_enrich_fixture() -> dict:
    """샘플 공고 몇 건에 대해 미리 만들어 둔 '30초 요약' (LLM 단계 결과 모양 확인용)."""
    path = FIXTURE_DIR / "enrich_sample.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
