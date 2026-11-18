#!/usr/bin/env python3
"""
월말 종가를 받아와서 Supabase market_prices 테이블에 저장 (GitHub Actions 에서 실행).

  python fetch_to_supabase.py                         # 자동: 최근 끝난 3개월 중 빈 칸만 채움
  python fetch_to_supabase.py --from 2026-09 --to 2026-10 --overwrite   # 기간 지정, 있는 값도 덮어쓰기
  python fetch_to_supabase.py --dry-run               # 받아오기만 하고 저장 안 함

환경변수: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import update_index as ui          # 시세 출처 코드 (맥용 스크립트와 같은 파일)
from assets import ASSETS

KST = ZoneInfo("Asia/Seoul")
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def api(method, path, body=None, prefer=None):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode())
    req.add_header("apikey", KEY)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt.strip() else None


def ym_add(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="ym_from")
    ap.add_argument("--to", dest="ym_to")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not URL or not KEY:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 가 설정되지 않았어요 (GitHub Secrets 확인).")

    today = dt.datetime.now(KST).date()
    last_done = ym_add(today.year, today.month, -1)          # 가장 최근에 끝난 달
    if a.ym_from or a.ym_to:
        lo = tuple(map(int, (a.ym_from or a.ym_to).split("-")))
        hi = tuple(map(int, (a.ym_to or a.ym_from).split("-")))
        hi = min(hi, last_done)
    else:
        lo, hi = ym_add(*last_done, -2), last_done             # 최근 3개월 빈 칸 확인
    months = []
    ym = lo
    while ym <= hi:
        months.append(ym)
        ym = ym_add(*ym, 1)
    if not months:
        print("채울 달이 없어요.")
        return 0

    rows = api("GET", f"market_prices?select=month,code&month=gte.{lo[0]}-{lo[1]:02d}-01"
                      f"&month=lte.{hi[0]}-{hi[1]:02d}-01")
    have = {(int(r["month"][:4]), int(r["month"][5:7]), r["code"]) for r in rows or []}

    need = {}
    for code, label, _ in ASSETS:
        ms = [ym for ym in months if a.overwrite or (ym[0], ym[1], code) not in have]
        if ms:
            need[code] = ms
    if not need:
        print(f"{months[0]}~{months[-1]}: 빈 칸 없음. 할 일 없음.")
        return 0

    print(f"받아올 항목 {len(need)}개, 기간 {months[0]} ~ {months[-1]}")
    upserts, missing = [], []
    for code, ms in need.items():
        label = dict((c, l) for c, l, _ in ASSETS)[code]
        got = ui.fetch_months(label, ms)
        for ym in ms:
            if ym in got:
                v, src = got[ym]
                upserts.append({"month": f"{ym[0]}-{ym[1]:02d}-01", "code": code,
                                "value": float(ui.fmt_num(v)), "source": src})
            else:
                missing.append(f"{ym[0]}-{ym[1]:02d} {code}({label})")
        print(f"  {code:<8} {label:<14} {len(got)}/{len(ms)}개월")

    if upserts and not a.dry_run:
        prefer = "resolution=merge-duplicates" if a.overwrite else "resolution=ignore-duplicates"
        for i in range(0, len(upserts), 500):
            api("POST", "market_prices?on_conflict=month,code", upserts[i:i + 500], prefer + ",return=minimal")
    print(f"{'(dry-run) ' if a.dry_run else ''}저장 {len(upserts)}칸")
    if missing:
        print("못 가져온 칸: " + ", ".join(missing))

    Path(__file__).with_name("last_run.json").write_text(json.dumps({
        "ran_at": dt.datetime.now(KST).isoformat(timespec="seconds"),
        "saved": len(upserts), "missing": missing,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # 재시도 마지막 날(5일)에 지난달 빈 칸이 남아 있으면 실패로 표시 → GitHub 가 메일로 알려줌
    last_tag = f"{last_done[0]}-{last_done[1]:02d} "
    if (not (a.ym_from or a.ym_to) and today.day == 5
            and any(x.startswith(last_tag) for x in missing)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
