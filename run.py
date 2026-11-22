#!/usr/bin/env python3
"""지원사업 레이더 파이프라인.

  python run.py all --sample   # API 키 없이 샘플 데이터로 전체 실행 (미리보기용)
  python run.py all            # 수집 → 요약 → 빌드 (BIZINFO_API_KEY 필요)
  python run.py fetch | enrich | build
  python run.py serve          # dist/를 http://localhost:8000 에서 보기
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """의존성 없이 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


def cmd_fetch(cfg) -> None:
    from pipeline import store
    from pipeline.config import now_kst, today_kst
    from pipeline.sources import bizinfo, sample

    today = today_kst()
    if cfg.sample:
        raw = sample.load_raw(today)
        print(f"[fetch] 샘플 데이터 {len(raw)}건을 불러옵니다.")
    else:
        key = os.environ.get("BIZINFO_API_KEY")
        if not key:
            sys.exit("[fetch] BIZINFO_API_KEY가 없습니다. .env에 넣거나, 먼저 --sample로 돌려보세요.")
        try:
            raw = bizinfo.fetch_items(key)
        except bizinfo.BizinfoError as e:
            sys.exit(f"[fetch] 기업마당 API 오류: {e}")
        print(f"[fetch] 기업마당에서 {len(raw)}건을 받았습니다.")

    incoming = [n for n in (bizinfo.normalize(r) for r in raw) if n]
    db = store.load_notices(cfg.data_dir)
    stats = store.upsert(db["items"], incoming, today)
    pruned = store.prune(db["items"], today, cfg.retain_closed_days)
    db["meta"] = {"mode": "sample" if cfg.sample else "live", "fetched_at": now_kst().isoformat(), "count": len(db["items"])}
    store.save_notices(cfg.data_dir, db)
    print(f"[fetch] 신규 {stats['new']} · 변경 {stats['changed']} · 동일 {stats['same']} · 정리 {pruned} → 총 {len(db['items'])}건")

    if cfg.sample:
        # 미리 만들어 둔 샘플 요약을 붙여서 '30초 요약' 화면을 API 키 없이도 볼 수 있게 한다.
        cache = store.load_enrich(cfg.data_dir)
        for nid, result in sample.load_enrich_fixture().items():
            if nid in db["items"]:
                cache[nid] = {"hash": db["items"][nid]["hash"], "model": "sample", "status": "ok", "result": result}
        store.save_enrich(cfg.data_dir, cache)


def cmd_enrich(cfg, limit: int | None) -> None:
    from pipeline import enrich

    enrich.run(cfg, limit=limit)


def cmd_build(cfg, drafts: bool) -> None:
    from pipeline import build

    if not cfg.sample and "example.com" in cfg.base_url:
        print("[build] 경고: base_url이 아직 example.com입니다. SITE_BASE_URL을 실제 주소로 설정하세요.")
    stats = build.build(cfg, include_drafts=drafts)
    print(f"[build] 페이지 {stats['pages']}개 생성 (진행 중 공고 {stats['active']} · 마감 임박 {stats['closing']} · 해설 {stats['posts']}) → dist/")


def cmd_serve(port: int, base_path: str) -> None:
    """dist/를 배포 주소와 같은 하위 경로(예: /gov-grants/)에 올려서 링크가 그대로 동작하게 한다."""
    import http.server

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)

        def do_GET(self):
            if base_path and not self.path.startswith(base_path + "/"):
                self.send_response(302)
                self.send_header("Location", base_path + "/")
                self.end_headers()
                return
            self.path = self.path[len(base_path):] or "/"
            super().do_GET()

    print(f"http://localhost:{port}{base_path}/ 에서 dist/를 보여줍니다. (Ctrl+C로 종료)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    load_dotenv(ROOT / ".env")
    sys.path.insert(0, str(ROOT))
    from pipeline.config import load_config

    p = argparse.ArgumentParser(description="지원사업 레이더 파이프라인")
    p.add_argument("command", choices=["fetch", "enrich", "build", "all", "serve", "queue", "import"])
    p.add_argument("files", nargs="*", help="import: Claude Code가 쓴 결과 파일들 (기본: data/<mode>/inbox.json)")
    p.add_argument("--sample", action="store_true", help="실데이터 대신 샘플 공고 사용 (data/sample/)")
    p.add_argument("--limit", type=int, default=None, help="요약할 최대 공고 수 (기본: 설정값)")
    p.add_argument("--drafts", action="store_true", help="draft: true인 해설 글도 포함")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    cfg = load_config(sample=args.sample)
    if args.command == "serve":
        return cmd_serve(args.port, cfg.base_path)
    if args.command in ("queue", "import"):
        from pipeline import enrich

        if args.command == "queue":
            enrich.export_queue(cfg, args.limit if args.limit is not None else cfg.llm_max_per_run)
        else:
            paths = [Path(f) for f in args.files] or [cfg.data_dir / enrich.INBOX_FILE]
            existing = [p for p in paths if p.exists()]
            if not existing:
                print("[import] 가져올 결과 파일이 없습니다.")
                return
            enrich.import_results(cfg, existing)
            for p in existing:
                p.unlink()
        return
    if args.command in ("fetch", "all"):
        cmd_fetch(cfg)
    if args.command in ("enrich", "all"):
        cmd_enrich(cfg, args.limit)
    if args.command in ("build", "all"):
        cmd_build(cfg, args.drafts)


if __name__ == "__main__":
    main()
