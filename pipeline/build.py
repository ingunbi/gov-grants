"""정적 사이트 생성: data/<mode>/notices.json + enrich.json + content/posts → dist/"""
from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import store
from .config import KST, ROOT, Config, now_kst, today_kst
from .sources.bizinfo import NATIONWIDE, REGIONS
from .status import notice_status, sort_key

CATEGORIES = {
    "창업": "startup",
    "금융": "finance",
    "기술": "tech",
    "인력": "hr",
    "수출": "export",
    "내수": "domestic",
    "경영": "management",
    "기타": "etc",
}
REGION_SLUGS = {
    NATIONWIDE: "nationwide",
    "서울": "seoul",
    "부산": "busan",
    "대구": "daegu",
    "인천": "incheon",
    "광주": "gwangju",
    "대전": "daejeon",
    "울산": "ulsan",
    "세종": "sejong",
    "경기": "gyeonggi",
    "강원": "gangwon",
    "충북": "chungbuk",
    "충남": "chungnam",
    "전북": "jeonbuk",
    "전남": "jeonnam",
    "경북": "gyeongbuk",
    "경남": "gyeongnam",
    "제주": "jeju",
}
assert set(REGION_SLUGS) == set(REGIONS) | {NATIONWIDE}

TEMPLATE_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
POSTS_DIR = ROOT / "content" / "posts"


def _fmt_date(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%Y.%m.%d") if value else ""


def period_display(n: dict) -> str:
    s, e = _fmt_date(n.get("start_date")), _fmt_date(n.get("end_date"))
    if s and e:
        return f"{s} ~ {e}"
    if e:
        return f"~ {e}"
    if n.get("period_kind") == "always":
        return n.get("period_raw") or "상시 접수"
    return n.get("period_raw") or "공고문 확인"


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _summary_snippet(n: dict) -> str:
    # '□ 사업목적:' 같은 머리말을 걷어내고 첫 두 줄만
    lines = [re.sub(r"^[□○◦•\-\s]*([^:：]{1,10}[:：])?\s*", "", ln) for ln in n.get("summary_text", "").split("\n")]
    return _clip(" / ".join(ln for ln in lines[:2] if ln), 90)


def prepare(n: dict, enrich: dict, today: date, cfg: Config) -> dict:
    v = dict(n)
    entry = enrich.get(n["id"])
    v["ai"] = entry["result"] if entry and entry.get("result") and entry.get("hash") == n["hash"] else None
    v.update(notice_status(n, today, cfg.closing_soon_days))
    v["cat_slug"] = CATEGORIES.get(n["category"], "etc")
    v["cat_name"] = n["category"] if n["category"] in CATEGORIES else "기타"
    v["region_links"] = [(r, REGION_SLUGS.get(r, "nationwide")) for r in n["regions"]]
    v["period_display"] = period_display(n)
    first = n.get("registered_at") or n.get("first_seen")
    v["is_new"] = bool(first) and (today - date.fromisoformat(first)).days < cfg.new_days
    v["snippet"] = (v["ai"] or {}).get("one_line") or _summary_snippet(n)
    v["meta_description"] = _clip(
        f"{v['snippet']} 신청기간 {v['period_display']}. {n.get('agency', '')} 공고를 한눈에 정리했습니다.", 155
    )
    ai = v["ai"] or {}
    v["card_amount"] = ai.get("amount") or "공고문 확인"
    v["card_target"] = " · ".join(ai.get("eligibility", [])[:2]) or n.get("target") or "공고문 확인"
    v["registered_sort"] = first or ""
    v["search_text"] = " ".join(
        [n["title"], n.get("agency", ""), n.get("executor", ""), v["card_target"], v["card_amount"], v["snippet"], v["cat_name"], " ".join(n.get("regions", [])), " ".join(n.get("hashtags", []))]
    ).lower()
    v["path"] = f"/notice/{n['id']}/"
    return v


def load_posts(include_drafts: bool) -> list[dict]:
    posts = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        body = raw
        if raw.startswith("---"):
            _, front, body = raw.split("---", 2)
            for line in front.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
        if meta.get("draft", "").lower() == "true" and not include_drafts:
            continue
        slug = meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
        posts.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "description": meta.get("description", ""),
                "date": meta.get("date", path.stem[:10]),
                "draft": meta.get("draft", "").lower() == "true",
                "html": markdown.markdown(body, extensions=["tables", "sane_lists"]),
                "path": f"/posts/{slug}/",
            }
        )
    return sorted(posts, key=lambda p: p["date"], reverse=True)


class Site:
    def __init__(self, cfg: Config, out: Path):
        self.cfg, self.out = cfg, out
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.urls: list[tuple[str, str]] = []  # (path, lastmod) for sitemap

    def page(self, path: str, template: str, lastmod: str | None = None, sitemap: bool = True, **ctx) -> None:
        html = self.env.get_template(template).render(page_path=path, canonical=self.cfg.site_url + path, **ctx)
        target = self.out / path.lstrip("/") / "index.html" if path.endswith("/") else self.out / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        if sitemap:
            self.urls.append((path, lastmod or today_kst().isoformat()))

    def text(self, rel: str, content: str) -> None:
        (self.out / rel).write_text(content, encoding="utf-8")


def build(cfg: Config, include_drafts: bool = False, out: Path | None = None) -> dict:
    out = out or ROOT / "dist"
    today = today_kst()
    db = store.load_notices(cfg.data_dir)
    enrich = store.load_enrich(cfg.data_dir)
    notices = [prepare(n, enrich, today, cfg) for n in db["items"].values()]
    active = sorted((n for n in notices if n["status"] != "closed"), key=sort_key)
    closing = [n for n in active if n["status"] == "closing"]
    fresh = sorted((n for n in active if n["is_new"]), key=lambda n: n.get("registered_at") or "", reverse=True)
    posts = load_posts(include_drafts or cfg.sample)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC_DIR, out / "assets")

    cat_counts = {name: sum(1 for n in active if n["cat_name"] == name) for name in CATEGORIES}
    region_counts = {name: sum(1 for n in active if name in n["regions"]) for name in REGION_SLUGS}
    site = Site(cfg, out)
    site.env.globals.update(
        site=cfg,
        base=cfg.base_path,
        sample=cfg.sample,
        today=today,
        updated_at=db.get("meta", {}).get("fetched_at", ""),
        categories=[(name, slug, cat_counts[name]) for name, slug in CATEGORIES.items()],
        regions=[(name, slug, region_counts[name]) for name, slug in REGION_SLUGS.items()],
        ads_enabled=bool(cfg.adsense_client),
        year=today.year,
    )

    site.page(
        "/",
        "index.html",
        notices=active,
        stats={"active": len(active), "closing": len(closing), "new": len(fresh)},
        posts=posts[:3],
    )
    site.page(
        "/closing-soon/",
        "list.html",
        title=f"이번 주 마감 지원사업 {len(closing)}건",
        intro=f"{cfg.closing_soon_days}일 안에 접수가 끝나는 공고입니다. 서류 준비에 시간이 걸리니 먼저 확인하세요.",
        notices=closing,
    )
    site.page(
        "/new/",
        "list.html",
        title=f"최근 {cfg.new_days}일 새로 올라온 지원사업",
        intro="새로 등록된 공고를 등록일 순으로 모았습니다.",
        notices=fresh,
    )
    for name, slug in CATEGORIES.items():
        items = [n for n in active if n["cat_name"] == name]
        site.page(
            f"/category/{slug}/",
            "list.html",
            title=f"{name} 분야 정부지원사업 공고",
            intro=f"지금 신청할 수 있는 {name} 분야 지원사업 {len(items)}건을 마감일 순으로 정리했습니다.",
            notices=items,
        )
    for name, slug in REGION_SLUGS.items():
        items = [n for n in active if name in n["regions"]]
        intro = (
            f"지역 제한 표시가 없는 전국 단위 공고 {len(items)}건입니다."
            if name == NATIONWIDE
            else f"{name} 지역 기업·창업자를 위한 지원사업 {len(items)}건입니다. 전국 공고는 '전국' 페이지에서 확인하세요."
        )
        site.page(f"/region/{slug}/", "list.html", title=f"{name} 지원사업 공고", intro=intro, notices=items)

    by_cat: dict[str, list[dict]] = {}
    for n in active:
        by_cat.setdefault(n["cat_name"], []).append(n)
    for n in notices:
        related = [r for r in by_cat.get(n["cat_name"], []) if r["id"] != n["id"]][:5]
        site.page(n["path"], "notice.html", lastmod=n.get("last_seen"), n=n, related=related)

    site.page("/posts/", "posts.html", posts=posts)
    for p in posts:
        site.page(p["path"], "post.html", lastmod=p["date"], post=p)
    site.page("/about/", "about.html")
    site.page("/404.html", "404.html", sitemap=False)

    _write_sitemap(site)
    _write_feed(site, cfg, sorted(active, key=lambda n: n.get("first_seen") or "", reverse=True)[:50])
    robots = "User-agent: *\nDisallow: /\n" if cfg.sample else f"User-agent: *\nAllow: /\nSitemap: {cfg.site_url}/sitemap.xml\n"
    site.text("robots.txt", robots)
    if cfg.adsense_client:
        pub = cfg.adsense_client.removeprefix("ca-")
        site.text("ads.txt", f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")

    return {"pages": len(site.urls) + 1, "active": len(active), "closing": len(closing), "posts": len(posts)}


def _write_sitemap(site: Site) -> None:
    rows = "\n".join(
        f"  <url><loc>{site.cfg.site_url}{path}</loc><lastmod>{lastmod}</lastmod></url>" for path, lastmod in site.urls
    )
    site.text(
        "sitemap.xml",
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}\n</urlset>\n',
    )


def _write_feed(site: Site, cfg: Config, items: list[dict]) -> None:
    def rfc822(day: str | None) -> str:
        d = date.fromisoformat(day) if day else today_kst()
        return format_datetime(datetime(d.year, d.month, d.day, 6, 0, tzinfo=KST))

    xml = site.env.get_template("feed.xml").render(items=items, build_date=format_datetime(now_kst()), rfc822=rfc822)
    site.text("feed.xml", xml)
