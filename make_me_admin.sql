-- 내 계정을 '내 자산'을 볼 수 있는 사람으로 등록 (Authentication 에서 사용자를 만든 뒤 Run)
-- 아래 이메일을 앱에 로그인할 이메일로 바꿔 주세요.
insert into public.app_admins (uid)
select id from auth.users where email = '여기에_내_이메일@example.com'
on conflict do nothing;

-- 확인: 1 이 나오면 성공
select count(*) as admins from public.app_admins;
