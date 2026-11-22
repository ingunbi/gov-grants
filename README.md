# 지원사업 레이더 (MVP)

기업마당 지원사업 공고를 매일 자동으로 모아 **마감일 순으로 정리**하고, 공고마다 **30초 요약**을 붙여 정적 사이트로 배포하는 파이프라인입니다.

```
[매일 06:00 KST, GitHub Actions]
  fetch   기업마당 API → data/live/notices.json (신규·변경 감지, 오래된 공고 정리)
  enrich  Claude가 새 공고만 구조화 요약 → data/live/enrich.json (캐시, 하루 최대 N건)
  build   Jinja 템플릿 → dist/ (공고·분야·지역·마감임박 페이지, sitemap, RSS)
  deploy  GitHub Pages
```

## 바로 돌려보기 (키 없이)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py all --sample
.venv/bin/python run.py serve      # http://localhost:8000
```

샘플 모드는 `data/sample/`에 따로 저장되고, 페이지에 경고 배너와 `noindex`가 붙습니다. 실데이터와 섞이지 않습니다.

## 실데이터로 돌리기

1. **기업마당 API 키**: <https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi> → 'API 사용 신청' (무료, 신청서에 시스템 IP를 적게 되어 있음)
2. **Claude API 키** (선택): 없으면 요약만 빠지고 사이트는 원문 정보로 빌드됩니다.
3. `.env.example`을 `.env`로 복사해서 키를 채운 뒤:

```bash
.venv/bin/python run.py all
```

## 배포 (GitHub Pages)

1. 이 폴더를 GitHub 저장소로 올립니다.
2. Settings → Pages → Source를 **GitHub Actions**로.
3. Settings → Secrets and variables → Actions:
   - Secrets: `BIZINFO_API_KEY`, `ANTHROPIC_API_KEY`
   - Variables: `SITE_BASE_URL` (예: `https://계정.github.io/저장소`, 자체 도메인이면 그 주소)
4. Actions 탭에서 `daily-update`를 한 번 수동 실행(Run workflow). 이후 매일 06:00에 자동으로 돕니다.

### Cloudflare로 배포 (Workers 정적 사이트)

`wrangler.jsonc`가 `dist/`를 Cloudflare Workers 정적 사이트로 올립니다. 로컬에서는:

```bash
npx wrangler deploy        # → https://gov-grants.<계정>.workers.dev
```

GitHub Actions에서 자동 배포하려면 Secrets에 `CLOUDFLARE_API_TOKEN`(대시보드 → My Profile → API Tokens → "Edit Cloudflare Workers" 템플릿)과 `CLOUDFLARE_ACCOUNT_ID`를, Variables에 `CF_BASE_URL`을 넣으세요. `CLOUDFLARE_API_TOKEN`이 있으면 워크플로가 GitHub Pages 대신 Cloudflare로 배포합니다.

> **IP 제한 주의**: 기업마당 키가 신청서에 적은 IP에서만 동작하면, IP가 매번 바뀌는 GitHub Actions에서는 호출이 막힐 수 있습니다. 첫 실행 로그에서 `[fetch]` 오류가 나면 고정 IP 서버(작은 VPS, 집 Mac의 cron 등)에서 `run.py fetch`를 돌리고 `data/live`만 커밋하는 방식으로 바꾸세요.

## Claude 구독으로 요약하기 (API 키 없이)

API 대신 Claude Code(Pro/Max 구독)로 요약할 수 있습니다. 매일 워크플로가 아래 순서로 돕니다.

```
run.py queue --limit 50   → data/live/queue.json (요약할 공고, 마감 임박 먼저)
claude -p prompts/summarize.md → data/live/inbox.json
run.py import             → 형식 검사 후 enrich.json에 반영
```

1. 내 컴퓨터 터미널에서 `claude setup-token` 실행 → 나온 토큰(1년 유효)을 복사
2. `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <계정>/<저장소>` 로 등록
3. 하루 처리 건수는 저장소 변수 `SUMMARY_LIMIT`(기본 50)로 조절

구독 사용량 한도를 같이 쓰므로, 한도에 걸린 날은 요약만 건너뛰고 사이트는 그대로 배포됩니다. 로컬에서 Claude Code 세션으로 직접 돌려도 같은 파일 흐름(`queue` → `prompts/summarize.md` → `import`)을 쓰면 됩니다.

## 설정 (`site.config.json`)

| 키 | 설명 |
|---|---|
| `site_name`, `tagline` | 사이트 이름·설명 |
| `base_url` | 정식 주소 (canonical, sitemap에 사용). 환경변수 `SITE_BASE_URL`이 우선 |
| `adsense_client`, `adsense_slot` | 애드센스 승인 후 입력하면 광고 스크립트, 광고 자리, `ads.txt`가 자동으로 들어감 |
| `closing_soon_days` | 며칠 남으면 '마감 임박'으로 볼지 (기본 7) |
| `retain_closed_days` | 마감 후 며칠까지 페이지를 유지할지 (기본 180) |
| `llm.model` | 요약 모델 (기본 `claude-opus-5-5`, 환경변수 `LLM_MODEL`로 덮어쓰기) |
| `llm.effort` | 요약 노력 수준 (기본 `low`) |
| `llm.max_per_run` | 한 번 실행에 요약할 최대 건수 (비용 상한) |

### 요약 비용

공고 1건의 입력은 약 2~3천 토큰, 출력은 수백 토큰입니다. 기본 모델(Claude Opus 5.5, 입력 $4 / 출력 $20 per 1M 토큰) 기준으로 **1건에 대략 1~3센트**, 하루 50건이면 월 수십 달러 수준입니다. 실행이 끝나면 `[enrich]` 로그에 실제 토큰 수가 찍히니 그걸로 확인하세요. 비용을 크게 줄이려면 `LLM_MODEL=claude-haiku-5-5`(입력 $0.10 / 출력 $0.50)로 바꾸고, 요약 품질을 몇 건 비교해 보세요. 요약은 공고 내용이 바뀌지 않는 한 다시 호출하지 않습니다.

## 해설 글 쓰기

`content/posts/YYYY-MM-DD-slug.md` 파일을 추가하면 `/posts/slug/`로 발행됩니다. 맨 위에 `title`, `description`, `date`를 적고, `draft: true`면 배포에서 빠집니다(샘플 모드나 `--drafts`에서만 보임). 검색 노출과 신뢰도는 자동 페이지보다 이런 사람이 쓴 해설 글에서 크게 차이가 납니다. 주 2~3편을 목표로 하세요.

## 테스트

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

`tests/test_enrich.py`는 실제 SDK로 요청을 만들되 로컬 가짜 서버가 받기 때문에 비용이 들지 않습니다.

## 다음 단계 후보

- **K-Startup 공고 추가**: 공공데이터포털 `창업진흥원_K-Startup 조회서비스`(데이터셋 15125364, `getAnnouncementInformation01`). `pipeline/sources/`에 수집기를 하나 더 만들고 같은 스키마로 `normalize`하면 됩니다.
- **마감 알림 뉴스레터**: `feed.xml`(RSS)을 스티비·메일침프의 RSS 자동 발송에 연결
- **Search Console / 네이버 서치어드바이저**에 사이트 등록 후 `sitemap.xml` 제출
- **애드센스 신청**: 해설 글이 어느 정도 쌓인 뒤 신청하는 편이 승인에 유리
