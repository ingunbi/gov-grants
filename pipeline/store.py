"""공고 DB(JSON 파일) 읽기/쓰기. git에 커밋해서 상태를 유지하는 걸 전제로 한다."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_notices(data_dir: Path) -> dict:
    return _load(data_dir / "notices.json", {"meta": {}, "items": {}})


def save_notices(data_dir: Path, db: dict) -> None:
    _save(data_dir / "notices.json", db)


def load_enrich(data_dir: Path) -> dict:
    return _load(data_dir / "enrich.json", {})


def save_enrich(data_dir: Path, cache: dict) -> None:
    _save(data_dir / "enrich.json", cache)


def upsert(items: dict[str, dict], incoming: list[dict], today: date) -> dict[str, int]:
    """새로 받은 공고를 DB에 합친다. first_seen은 유지하고 last_seen은 갱신."""
    stats = {"new": 0, "changed": 0, "same": 0}
    t = today.isoformat()
    for n in incoming:
        old = items.get(n["id"])
        n["last_seen"] = t
        if old is None:
            n["first_seen"] = t
            stats["new"] += 1
        else:
            n["first_seen"] = old.get("first_seen", t)
            stats["changed" if old.get("hash") != n["hash"] else "same"] += 1
        items[n["id"]] = n
    return stats


def prune(items: dict[str, dict], today: date, retain_days: int) -> int:
    """마감 후 오래된 공고, 원본에서 사라진 지 오래된 공고를 지운다."""
    cutoff = (today - timedelta(days=retain_days)).isoformat()
    drop = [
        k
        for k, n in items.items()
        if (n.get("end_date") and n["end_date"] < cutoff) or (n.get("last_seen", cutoff) < cutoff)
    ]
    for k in drop:
        del items[k]
    return len(drop)
