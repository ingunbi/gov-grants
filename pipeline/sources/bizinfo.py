"""기업마당(bizinfo.go.kr) 지원사업정보 API 수집기.

API 문서: https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi
인증키는 같은 페이지의 'API 사용 신청'에서 무료로 발급받는다.

응답 필드는 두 벌(JSON용 pblancNm 계열, RSS용 title 계열)이 문서에 함께 나와 있어서
normalize()는 둘 다 받아들인다.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

API_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SITE_URL = "https://www.bizinfo.go.kr"
SOURCE_ID = "bizinfo"
SOURCE_NAME = "기업마당"

REGIONS: dict[str, tuple[str, ...]] = {
    "서울": ("서울", "서울시", "서울특별시"),
    "부산": ("부산", "부산시", "부산광역시"),
    "대구": ("대구", "대구시", "대구광역시"),
    "인천": ("인천", "인천시", "인천광역시"),
    "광주": ("광주", "광주시", "광주광역시"),
    "대전": ("대전", "대전시", "대전광역시"),
    "울산": ("울산", "울산시", "울산광역시"),
    "세종": ("세종", "세종시", "세종특별자치시"),
    "경기": ("경기", "경기도"),
    "강원": ("강원", "강원도", "강원특별자치도"),
    "충북": ("충북", "충청북도"),
    "충남": ("충남", "충청남도"),
    "전북": ("전북", "전라북도", "전북특별자치도"),
    "전남": ("전남", "전라남도"),
    "경북": ("경북", "경상북도"),
    "경남": ("경남", "경상남도"),
    "제주": ("제주", "제주도", "제주특별자치도"),
}
# 문서의 해시태그 목록에 묶여서 나오는 지역 태그
COMBINED_REGION_TAGS = {"전남광주": ("전남", "광주")}
_REGION_BY_ALIAS = {alias: name for name, aliases in REGIONS.items() for alias in aliases}
NATIONWIDE = "전국"

ALWAYS_WORDS = ("상시", "수시", "소진")
_DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]?\s*(\d{1,2})\s*[.\-/월]?\s*(\d{1,2})")


class BizinfoError(RuntimeError):
    pass


def fetch_items(api_key: str, search_cnt: int = 0, timeout: int = 90) -> list[dict]:
    """API를 호출해 원본 공고 목록을 돌려준다. search_cnt=0이면 전체를 받는다."""
    query = urlencode({"crtfcKey": api_key, "dataType": "json", "searchCnt": search_cnt})
    req = Request(f"{API_URL}?{query}", headers={"User-Agent": "jiwon-radar/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise BizinfoError(f"JSON이 아닌 응답을 받았습니다: {body[:200]!r}") from e
    if isinstance(data, dict) and data.get("reqErr"):
        raise BizinfoError(str(data["reqErr"]))
    return extract_items(data)


def extract_items(data) -> list[dict]:
    """jsonArray가 배열이든 {item: [...]} 형태든 공고 리스트만 꺼낸다."""
    payload = data.get("jsonArray", data) if isinstance(data, dict) else data
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        items = payload.get("item", [])
        if isinstance(items, dict):
            return [items]
        return [x for x in items if isinstance(x, dict)]
    return []


def parse_period(raw: str) -> tuple[date | None, date | None, str]:
    """신청기간 문자열 → (시작일, 마감일, 종류). 종류: range | always | unknown."""
    text = (raw or "").strip()
    found: list[tuple[int, date]] = []
    for m in _DATE_RE.finditer(text):
        try:
            found.append((m.start(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        except ValueError:
            continue
    if len(found) >= 2:
        return found[0][1], found[-1][1], "range"
    if any(w in text for w in ALWAYS_WORDS):
        return (found[0][1] if found else None), None, "always"
    if len(found) == 1:
        pos, d = found[0]
        tilde = text.find("~")
        if tilde != -1 and tilde < pos:
            return None, d, "range"  # "~ 2026.12.31" 처럼 마감일만 있는 경우
        return d, None, "unknown"
    return None, None, "unknown"


def html_to_text(value: str) -> str:
    """공고 본문 HTML을 줄 단위 일반 텍스트로 바꾼다."""
    if not value:
        return ""
    s = value
    if "&lt;" in s:  # 엔티티로 한 번 더 감싸서 오는 경우
        s = html.unescape(s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|table)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ").replace("\r", "")
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def extract_regions(hashtags: list[str]) -> list[str]:
    found: list[str] = []
    for tag in hashtags:
        names = COMBINED_REGION_TAGS.get(tag) or ((_REGION_BY_ALIAS[tag],) if tag in _REGION_BY_ALIAS else ())
        for name in names:
            if name not in found:
                found.append(name)
    order = list(REGIONS)
    return sorted(found, key=order.index)


def _split_list(value: str, sep: str) -> list[str]:
    return [p.strip() for p in (value or "").split(sep) if p.strip()]


def _attachments(urls: str, names: str) -> list[dict]:
    us, ns = _split_list(urls, "@"), _split_list(names, "@")
    return [
        {"name": ns[i] if i < len(ns) else f"첨부파일 {i + 1}", "url": urljoin(SITE_URL, u)}
        for i, u in enumerate(us)
    ]


def _to_int(value: str) -> int:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def content_hash(n: dict) -> str:
    keys = ("title", "category", "target", "period_raw", "summary_text", "apply_method")
    blob = json.dumps({k: n.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def normalize(item: dict) -> dict | None:
    """원본 공고 1건 → 사이트에서 쓰는 공통 스키마. 필수값이 없으면 None."""

    def pick(*keys: str) -> str:
        for k in keys:
            v = item.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    nid = pick("pblancId", "seq")
    title = html.unescape(pick("pblancNm", "title"))
    if not nid or not title:
        return None

    period_raw = pick("reqstBeginEndDe", "reqstDt")
    start, end, kind = parse_period(period_raw)
    hashtags = [t.strip("# ") for t in re.split(r"[,，]", pick("hashtags", "hashTags")) if t.strip("# ")]
    link = pick("pblancUrl", "link")
    print_url = pick("printFlpthNm")

    notice = {
        "id": nid,
        "source": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "title": title,
        "url": urljoin(SITE_URL, link) if link else "",
        "agency": pick("jrsdInsttNm", "author"),
        "executor": pick("excInsttNm"),
        "category": pick("pldirSportRealmLclasCodeNm", "lcategory") or "기타",
        "target": pick("trgetNm"),
        "summary_text": html_to_text(pick("bsnsSumryCn", "description")),
        "apply_method": html_to_text(pick("reqstMthPapersCn")),
        "contact": html_to_text(pick("refrncNm")),
        "apply_url": pick("rceptEngnHmpgUrl"),
        "period_raw": period_raw,
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "period_kind": kind,
        "hashtags": hashtags,
        "regions": extract_regions(hashtags) or [NATIONWIDE],
        "registered_at": (pick("creatPnttm", "pubDate")[:10] or None),
        "views": _to_int(pick("inqireCo")),
        "attachments": _attachments(pick("flpthNm"), pick("fileNm")),
        "print_file": (
            {"name": pick("printFileNm") or "공고문", "url": urljoin(SITE_URL, print_url)} if print_url else None
        ),
    }
    notice["hash"] = content_hash(notice)
    return notice
