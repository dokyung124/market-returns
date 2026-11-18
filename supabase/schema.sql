-- 월말 종가 테이블 (Supabase > SQL Editor 에 붙여넣고 Run)
create table if not exists public.market_prices (
  month      date    not null,          -- 그 달 1일 (예: 2026-10-01 = 10월 월말 종가)
  code       text    not null,          -- 종목 코드 (SPX, KOSPI, USDKRW ...)
  value      numeric not null,          -- 종가 (현지 통화 기준, 환율은 1단위당 원화)
  source     text,                      -- 어디서 가져왔는지
  updated_at timestamptz not null default now(),
  primary key (month, code)
);

-- 누구나 읽기만 가능 (시장 데이터라 공개돼도 괜찮음). 쓰기는 GitHub Actions(service_role 키)만.
alter table public.market_prices enable row level security;
drop policy if exists "public read" on public.market_prices;
create policy "public read" on public.market_prices for select using (true);
