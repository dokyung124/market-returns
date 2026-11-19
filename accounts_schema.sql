-- 내 자산(절세계좌) 테이블 — 로그인한 "관리자"만 보고 고칠 수 있어요.
-- Supabase > SQL Editor 에 붙여넣고 Run

-- 1) 볼 수 있는 사람 목록 (본인 계정만 넣을 거예요)
create table if not exists public.app_admins (
  uid uuid primary key references auth.users(id) on delete cascade
);
alter table public.app_admins enable row level security;
drop policy if exists "self read" on public.app_admins;
create policy "self read" on public.app_admins for select using (uid = auth.uid());

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.app_admins where uid = auth.uid());
$$;

-- 2) 계좌 목록
create table if not exists public.accounts (
  id     text primary key,          -- ISA, PEN_TAX, PEN_NOTAX, IRP ...
  name   text not null,             -- 앱에 보이는 이름
  broker text,                      -- 한국투자증권 등
  grp    text default '절세계좌',    -- 묶음 (합계 계산용)
  sort   int default 0
);

-- 3) 계좌별 월말 기록 (엑셀 '○○ 계좌 현황' 탭의 일자·계좌 총액·입금액·월간 배당금)
create table if not exists public.account_monthly (
  month      date    not null,      -- 그 달 1일 (예: 2026-10-01 = 10월 말 기준)
  account_id text    not null references public.accounts(id) on delete cascade,
  total      numeric not null,      -- 계좌 총액 (평가금액 + 예수금)
  deposit    numeric not null default 0,  -- 그 달 입금액
  dividend   numeric not null default 0,  -- 그 달 배당금
  source     text,                  -- 엑셀 / 한국투자증권 API / 직접 입력
  deposit_auto boolean not null default false,  -- 입금액을 자동으로 추정했는지 (앱에서 확인 표시)
  updated_at timestamptz not null default now(),
  primary key (month, account_id)
);

-- 4) 계좌별 월말 보유 종목 (API 연결 후부터 쌓여요)
create table if not exists public.holdings_monthly (
  month       date    not null,
  account_id  text    not null references public.accounts(id) on delete cascade,
  symbol      text    not null,     -- 종목코드
  name        text,
  qty         numeric,
  avg_price   numeric,              -- 평단가
  price       numeric,              -- 월말 현재가
  eval_amount numeric,              -- 평가금액
  profit      numeric,              -- 평가손익
  updated_at  timestamptz not null default now(),
  primary key (month, account_id, symbol)
);

-- 5) 보안: 관리자만 읽기·수정 (GitHub Actions 는 Secret key 라서 이 규칙과 상관없이 저장 가능)
alter table public.accounts         enable row level security;
alter table public.account_monthly  enable row level security;
alter table public.holdings_monthly enable row level security;

drop policy if exists "admin all" on public.accounts;
drop policy if exists "admin all" on public.account_monthly;
drop policy if exists "admin all" on public.holdings_monthly;
create policy "admin all" on public.accounts         for all using (public.is_admin()) with check (public.is_admin());
create policy "admin all" on public.account_monthly  for all using (public.is_admin()) with check (public.is_admin());
create policy "admin all" on public.holdings_monthly for all using (public.is_admin()) with check (public.is_admin());
