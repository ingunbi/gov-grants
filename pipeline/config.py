"""사이트 설정, 경로, 날짜 기준(KST)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 고정 오프셋으로 충분


def today_kst() -> date:
    """오늘 날짜(KST). 테스트나 재현용으로 TODAY=YYYY-MM-DD 환경변수로 덮어쓸 수 있다."""
    override = os.environ.get("TODAY")
    if override:
        return date.fromisoformat(override)
    return datetime.now(KST).date()


def now_kst() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


@dataclass
class Config:
    site_name: str
    tagline: str
    base_url: str
    adsense_client: str
    adsense_slot: str
    closing_soon_days: int
    new_days: int
    retain_closed_days: int
    llm_model: str
    llm_effort: str
    llm_max_per_run: int
    sample: bool = False

    @property
    def base_path(self) -> str:
        """하위 경로 배포(예: GitHub Pages 프로젝트 사이트)용 링크 접두어. 루트 배포면 ''."""
        return urlparse(self.base_url).path.rstrip("/")

    @property
    def site_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def data_dir(self) -> Path:
        # 샘플 데이터와 실데이터가 절대 섞이지 않도록 폴더를 분리한다.
        return ROOT / "data" / ("sample" if self.sample else "live")


def load_config(sample: bool = False) -> Config:
    raw = json.loads((ROOT / "site.config.json").read_text(encoding="utf-8"))
    llm = raw.get("llm", {})
    return Config(
        site_name=raw["site_name"],
        tagline=raw["tagline"],
        base_url=os.environ.get("SITE_BASE_URL") or raw["base_url"],
        adsense_client=os.environ.get("ADSENSE_CLIENT") or raw.get("adsense_client", ""),
        adsense_slot=os.environ.get("ADSENSE_SLOT") or raw.get("adsense_slot", ""),
        closing_soon_days=int(raw.get("closing_soon_days", 7)),
        new_days=int(raw.get("new_days", 7)),
        retain_closed_days=int(raw.get("retain_closed_days", 180)),
        llm_model=os.environ.get("LLM_MODEL") or llm.get("model", "claude-opus-5-5"),
        llm_effort=os.environ.get("LLM_EFFORT") or llm.get("effort", "low"),
        llm_max_per_run=int(os.environ.get("LLM_MAX_PER_RUN") or llm.get("max_per_run", 50)),
        sample=sample,
    )
