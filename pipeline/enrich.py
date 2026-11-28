"""공고 '30초 요약'을 Claude 구독(Claude Code)으로 만든다.

  1) run.py queue  → data/<mode>/queue.json : 요약할 공고 원문 목록 (마감 임박 → 최신 등록 순)
  2) claude -p prompts/summarize.md          : Claude Code가 data/<mode>/inbox.json을 작성
  3) run.py import → 형식 검사 후 data/<mode>/enrich.json에 반영

요약은 공고 id + 내용 해시로 캐시되므로, 내용이 바뀌지 않은 공고는 다시 요약하지 않는다.
마감된 공고는 대기열에 넣지 않는다. 요약이 없어도 사이트는 원문 정보로 빌드된다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re

from .config import Config, now_kst, today_kst
from .status import notice_status
from .sources.documents import attachment_text
from . import store

QUEUE_FILE = "queue.json"
INBOX_FILE = "inbox.json"

# Claude Code가 쓰는 결과 1건의 형식. 규칙 문서는 prompts/summarize.md (필드를 바꾸면 둘 다 고친다)
SCHEMA = {
    "type": "object",
    "properties": {
        "one_line": {"type": "string", "description": "누가 무엇을 받는지 중심의 한 문장 요약, 60자 이내"},
        "eligibility": {"type": "array", "items": {"type": "string"}, "description": "신청 자격·대상 조건, 최대 5개"},
        "benefits": {"type": "array", "items": {"type": "string"}, "description": "지원 내용, 최대 5개"},
        "amount": {"type": "string", "description": "지원 규모·한도·선정 규모. 원문에 없으면 빈 문자열"},
        "how_to_apply": {"type": "array", "items": {"type": "string"}, "description": "신청 방법·절차·제출서류 핵심, 최대 4개"},
        "check_before": {"type": "array", "items": {"type": "string"}, "description": "신청 전 확인할 제한·제외 조건, 최대 3개"},
        "good_for": {"type": "string", "description": "이 사업이 특히 맞는 사람·기업 한 문장. 근거가 약하면 빈 문자열"},
    },
    "required": ["one_line", "eligibility", "benefits", "amount", "how_to_apply", "check_before", "good_for"],
    "additionalProperties": False,
}


# 원문·첨부에 <notice>, </notice>를 흉내 낸 문자열이 있으면 자료 구간이 일찍 끝난 것처럼 보일 수 있다.
# 그 태그의 '<'만 전각 '＜'로 바꾼다. html.escape는 쓰지 않는다: "R&D"가 "R&amp;D"로 AI에 들어가 요약에 그대로 옮겨진다.
NOTICE_TAG = re.compile(r"<(?=\s*/?\s*notice\b)", re.IGNORECASE)


def _neutralize_tags(text: str) -> str:
    return NOTICE_TAG.sub("＜", str(text))


def build_notice_text(n: dict, document: str = "") -> str:
    """queue.json에 넣을 공고 원문. <notice>로 감싸 '자료'임을 분명히 한다."""
    fields = [
        ("공고명", n.get("title")),
        ("소관기관", n.get("agency")),
        ("수행기관", n.get("executor")),
        ("지원분야", n.get("category")),
        ("지원대상(원문)", n.get("target")),
        ("신청기간(원문)", n.get("period_raw")),
        ("사업개요(원문)", n.get("summary_text")),
        ("신청방법(원문)", n.get("apply_method")),
        ("문의처", n.get("contact")),
        ("공식 첨부 발췌", document),
    ]
    body = "\n\n".join(f"[{k}]\n{_neutralize_tags(v)}" for k, v in fields if v)
    return f"<notice>\n{body}\n</notice>"


def select_targets(cfg: Config, db: dict, cache: dict) -> list[dict]:
    """요약이 필요한 공고: 캐시에 없거나 내용이 바뀐 진행 중 공고. 마감 임박 → 최신 등록 순."""
    today = today_kst()
    targets = []
    for n in db["items"].values():
        entry = cache.get(n["id"])
        if entry is not None and entry.get("hash") == n["hash"]:
            continue
        st = notice_status(n, today, cfg.closing_soon_days)
        if st["status"] == "closed":
            continue
        targets.append((st, n))
    # 안정 정렬 두 번: 최신 등록 순으로 깔고, 그 위에 마감 임박(남은 날짜 적은 순)을 올린다.
    targets.sort(key=lambda t: (t[1].get("registered_at") or "", t[1]["id"]), reverse=True)
    targets.sort(key=lambda t: (t[0]["status"] != "closing", t[0]["days_left"] if t[0]["status"] == "closing" else 0))
    return [n for _, n in targets]


def export_queue(cfg: Config, limit: int) -> int:
    db = store.load_notices(cfg.data_dir)
    cache = store.load_enrich(cfg.data_dir)
    targets = select_targets(cfg, db, cache)
    selected = targets[:limit]
    if cfg.sample:
        documents = [""] * len(selected)
    else:
        with ThreadPoolExecutor(max_workers=6) as executor:
            documents = list(executor.map(attachment_text, selected))
    batch = [
        {"id": n["id"], "hash": n["hash"], "notice": build_notice_text(n, document)}
        for n, document in zip(selected, documents, strict=True)
    ]
    print(f"[queue] 공식 첨부 텍스트 확보 {sum(bool(doc) for doc in documents)}건")
    path = cfg.data_dir / QUEUE_FILE
    path.write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[queue] {len(batch)}건을 {path.relative_to(cfg.data_dir.parent.parent)}에 썼습니다. (전체 대기 {len(targets)}건)")
    return len(batch)


def validate_result(obj) -> dict | None:
    """Claude Code가 쓴 결과 1건이 SCHEMA를 지키는지 확인하고, 다듬은 dict를 돌려준다."""
    if not isinstance(obj, dict):
        return None
    props = SCHEMA["properties"]
    if set(obj) != set(props):
        return None
    clean = {}
    for key, spec in props.items():
        value = obj[key]
        if spec["type"] == "string":
            if not isinstance(value, str):
                return None
            clean[key] = value.strip()
        else:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                return None
            clean[key] = [x.strip() for x in value if x.strip()]
    return clean if clean["one_line"] else None


def import_results(cfg: Config, paths: list) -> dict:
    db = store.load_notices(cfg.data_dir)
    cache = store.load_enrich(cfg.data_dir)
    stats = {"ok": 0, "invalid": 0, "stale": 0}
    for path in paths:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows if isinstance(rows, list) else []:
            n = db["items"].get(row.get("id")) if isinstance(row, dict) else None
            if n is None or row.get("hash") != n["hash"]:
                stats["stale"] += 1  # 그사이 공고가 바뀌었거나 없는 id
                continue
            result = validate_result(row.get("result"))
            if result is None:
                stats["invalid"] += 1
                continue
            cache[n["id"]] = {
                "hash": n["hash"],
                "model": "claude-code",
                "at": now_kst().isoformat(),
                "status": "ok",
                "result": result,
            }
            stats["ok"] += 1
    store.save_enrich(cfg.data_dir, cache)
    print(f"[import] 반영 {stats['ok']} · 형식 오류 {stats['invalid']} · 지난 내용 {stats['stale']}")
    return stats
