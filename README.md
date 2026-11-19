# 시장 수익률 앱

지수·환율·코인·원자재 32개의 월말 종가를 매달 1일 자동으로 모으고,
기간과 종목을 골라 **누적 수익률**을 그래프로 비교하는 앱이에요.

- 화면: GitHub Pages (아이폰 홈 화면에 앱처럼 추가)
- 데이터: Supabase `market_prices` 테이블
- 자동 입력: GitHub Actions 가 매월 1일 10:05(한국 시간)에 실행 → 맥이 꺼져 있어도 됨
  - 못 받아온 칸은 5일까지 매일 다시 시도하고, 5일에도 지난달 값이 비어 있으면 GitHub 가 메일로 알려줘요.

## 폴더 구성
| 파일 | 하는 일 |
|---|---|
| `index.html` | 앱 화면 (위쪽 `APP_CONFIG` 에 Supabase 주소·anon 키 입력) |
| `manifest.webmanifest`, `sw.js`, `icons/` | 아이폰 홈 화면 설치용 |
| `supabase/schema.sql` | 테이블 만들기 |
| `supabase/seed.sql` | 엑셀의 2023-12 ~ 2026-10 데이터 넣기 |
| `fetcher/` | 시세 받아오는 파이썬 코드 (맥 엑셀용 스크립트와 같은 출처 사용) |
| `.github/workflows/monthly-prices.yml` | 매월 자동 실행 설정 |

## 설치 순서

### 1. Supabase 에 테이블 만들기
1. Supabase 에서 프로젝트를 열어요. 가족캘린더처럼 **이미 쓰는 프로젝트에 테이블만 추가해도 돼요.**
   (무료 프로젝트는 일주일 동안 아무도 안 쓰면 잠드는데, 이 앱은 매주 월요일에 한 번씩 깨워요.)
2. 왼쪽 **SQL Editor** → New query → `supabase/schema.sql` 내용을 붙여넣고 **Run**
3. 새 query → `supabase/seed.sql` 내용을 붙여넣고 **Run** (1,120줄이 들어가요)
4. **Project Settings** 에서 세 가지를 메모해 둬요.
   - Project URL (`https://xxxx.supabase.co`) — Data API 메뉴
   - **Publishable key** (`sb_publishable_...`) → 앱 화면(index.html)에 넣을 키 — API Keys 메뉴
   - **Secret key** (`sb_secret_...`) → **GitHub Secrets 에만** 넣을 키 (파일에 절대 쓰지 마세요) — API Keys 메뉴 아래쪽
   - 예전 방식 키(anon / service_role, `eyJ...`)도 되지만 2027년 초에 없어질 예정이라 새 키를 쓰세요.

### 2. GitHub 저장소 만들고 파일 올리기
1. GitHub → **New repository** → 이름 예: `market-returns`, **Public** 으로 만들기
2. **uploading an existing file** 을 누르고 이 폴더 안의 파일과 폴더를 전부 끌어다 놓기
   - ⚠️ 맥 Finder 는 `.github` 폴더를 숨겨요. Finder 에서 `⌘ + Shift + .` 을 누르면 보여요.
   - 그래도 안 올라가면: 저장소 **Actions** 탭 → *set up a workflow yourself* →
     파일 이름을 `monthly-prices.yml` 로 하고 `.github/workflows/monthly-prices.yml` 내용을 붙여넣어 저장
3. `index.html` 을 열고 ✏️(연필) → 위쪽 `APP_CONFIG` 에 Project URL 과 Publishable key 입력 → Commit

### 3. 자동 입력에 쓸 비밀 키 넣기
저장소 **Settings → Secrets and variables → Actions → New repository secret** 로 두 개 추가
| Name | Secret |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret key (`sb_secret_...`) |

### 4. 앱 주소 열기 (GitHub Pages)
1. **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main` / `/ (root)` → Save
2. 1~2분 뒤 `https://아이디.github.io/market-returns/` 로 접속돼요.
3. 아이폰 Safari 로 열고 **공유 → 홈 화면에 추가**

### 5. 자동 입력 시험해 보기
1. 저장소 **Actions** 탭 → **월말 종가 자동 입력** → **Run workflow**
2. `dry_run` 에 체크하고 실행 → 끝나면 눌러서 로그 확인
   - 종목마다 `3/3개월` 처럼 나오면 정상이에요. (`빈 칸 없음. 할 일 없음.` 이 나와도 정상)
3. 문제없으면 12월 1일부터 자동으로 들어가요.

## 직접 실행 (필요할 때만)
Actions → 월말 종가 자동 입력 → Run workflow 에서
- `from`, `to` 에 달을 넣으면 그 기간을 채워요 (예: 2026-09 ~ 2026-10)
- `overwrite` 를 체크하면 이미 있는 값도 다시 받아와서 덮어써요

## 참고
- 그래프의 기준(0%)은 **고른 시작 달의 월말 종가**예요.
- **원화 환산**은 해외 종목에 그달 말 환율을 곱해서 계산해요. 한국 종목과 환율 자체는 그대로예요.
- 데이터가 중간부터 있는 종목은 순위 아래에 "○○부터 계산" 이라고 표시돼요.
- 맥의 엑셀 자동 입력은 이것과 따로 계속 돌아가요.

## 내 자산 (로그인한 본인만)
절세계좌(ISA·연금저축·IRP)의 월별 계좌 총액·입금액·수익률과 보유 종목을 보여줘요.
- Supabase: `supabase/accounts_schema.sql` → (개인 기록 SQL, 저장소에 올리지 않음) → Authentication 에서 내 계정 만들기 → `supabase/make_me_admin.sql`
- 매월 1일 07:05·08:05(장 시작 전): `.github/workflows/monthly-accounts.yml` 이 한국투자증권 잔고를 저장해요.
  - GitHub Secret `KIS_ACCOUNTS` 필요 (형식은 `fetcher/kis_accounts.py` 맨 위 설명)
  - 입금액은 API 로 알 수 없어서 지난달 값으로 넣고 앱에 "확인 필요"로 표시해요. 앱의 '고치기'로 바로잡을 수 있어요.
  - Actions 로그에는 금액·종목·계좌번호가 나오지 않아요.
- 맥에서 미리 확인: 홈 폴더에 `kis_accounts.json` 을 만들고 `python3 fetcher/kis_accounts.py --check`
