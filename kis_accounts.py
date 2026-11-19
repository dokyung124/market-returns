#!/usr/bin/env python3
"""
한국투자증권 계좌 잔고 → Supabase (내 자산) 매달 저장

  python kis_accounts.py --check            # 맥에서 시험: 잔고를 받아서 화면에만 보여줌 (저장 안 함)
  python kis_accounts.py --save             # GitHub Actions: 지난달 말 잔고 저장 (로그에는 금액이 안 나와요)
  python kis_accounts.py --save --month 2026-11 --force   # 날짜와 상관없이 저장 (장중이면 값이 월말과 달라요)

설정 (환경변수)
  KIS_ACCOUNTS  JSON 목록. 예:
    [{"id": "ISA",       "cano": "12345678", "prdt": "01", "app_key": "...", "app_secret": "..."},
     {"id": "PEN_TAX",   "cano": "23456789", "prdt": "22", "app_key": "...", "app_secret": "..."},
     {"id": "PEN_NOTAX", "cano": "34567890", "prdt": "22", "app_key": "...", "app_secret": "..."},
     {"id": "IRP",       "cano": "45678901", "prdt": "29", "app_key": "...", "app_secret": "..."}]
    - id 는 Supabase accounts 표의 id 와 같아야 해요.
    - 앱키를 여러 계좌가 같이 쓰면 계좌마다 같은 값을 넣으면 돼요.
    - "kind": "stock" | "pension" 으로 조회 방식을 정할 수 있어요 (안 쓰면 29 는 pension, 나머지는 stock→pension 순서로 시도).
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  (--save 일 때)

보안: --save 모드는 금액·종목·계좌번호를 출력하지 않아요 (공개 저장소의 Actions 로그는 누구나 볼 수 있기 때문).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BASE = os.environ.get("KIS_BASE", "https://openapi.koreainvestment.com:9443")
QUIET = False          # --save 일 때 True: 민감한 내용 출력 안 함


def say(*a):
    print(*a, flush=True)


class KisError(Exception):
    pass


# ----------------------------------------------------------------- KIS API
_tokens: dict[str, str] = {}


def token(app_key, app_secret):
    if app_key in _tokens:
        return _tokens[app_key]
    body = json.dumps({"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}).encode()
    req = urllib.request.Request(f"{BASE}/oauth2/tokenP", data=body, method="POST",
                                 headers={"content-type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise KisError(f"토큰 발급 실패 (HTTP {e.code}). 앱키·앱시크릿을 확인하세요. 1분 안에 다시 발급하면 거절될 수 있어요.")
    if "access_token" not in j:
        raise KisError(f"토큰 발급 실패: {j.get('error_description') or j.get('msg1') or '응답 이상'}")
    _tokens[app_key] = j["access_token"]
    return j["access_token"]


def kis_get(acc, path, tr_id, params, max_pages=20):
    """페이지를 넘기면서 output1 을 모두 모으고 마지막 output2 를 돌려줌."""
    tok = token(acc["app_key"], acc["app_secret"])
    rows, out2, tr_cont = [], None, ""
    params = dict(params)
    for _ in range(max_pages):
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {tok}",
            "appkey": acc["app_key"], "appsecret": acc["app_secret"], "tr_id": tr_id, "custtype": "P", "tr_cont": tr_cont})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode())
                next_cont = r.headers.get("tr_cont", "")
        except urllib.error.HTTPError as e:
            raise KisError(f"{tr_id} HTTP {e.code}")
        if j.get("rt_cd") != "0":
            raise KisError(f"{tr_id} 실패: [{j.get('msg_cd')}] {j.get('msg1', '').strip()}")
        o1 = j.get("output1") if "output1" in j else j.get("output")
        if isinstance(o1, list):
            rows += o1
        elif isinstance(o1, dict):
            rows.append(o1)
        o2 = j.get("output2")
        if o2:
            out2 = o2[0] if isinstance(o2, list) else o2
        if next_cont in ("F", "M") and j.get("ctx_area_nk100", "").strip():
            params["CTX_AREA_FK100"] = j.get("ctx_area_fk100", "")
            params["CTX_AREA_NK100"] = j.get("ctx_area_nk100", "")
            tr_cont = "N"
            time.sleep(0.25)
            continue
        break
    return rows, out2 or {}


def num(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", ""))
            except ValueError:
                pass
    return None


def parse_holdings(rows):
    out = []
    for h in rows:
        qty = num(h, "hldg_qty", "hold_qty", "ccld_qty_smtl")
        if not qty:
            continue
        out.append({"symbol": (h.get("pdno") or h.get("prdt_cd") or "").strip(),
                    "name": (h.get("prdt_name") or h.get("prdt_abrv_name") or "").strip(),
                    "qty": qty,
                    "avg_price": num(h, "pchs_avg_pric", "pchs_avg_unpr"),
                    "price": num(h, "prpr", "stck_prpr", "now_pric"),
                    "eval_amount": num(h, "evlu_amt", "evlu_amt_smtl"),
                    "profit": num(h, "evlu_pfls_amt", "evlu_pfls_amt_smtl")})
    return out


def fetch_stock(acc):
    rows, o2 = kis_get(acc, "/uapi/domestic-stock/v1/trading/inquire-balance", "TTTC8434R", {
        "CANO": acc["cano"], "ACNT_PRDT_CD": acc["prdt"], "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
        "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
    holdings = parse_holdings(rows)
    total = num(o2, "tot_evlu_amt")
    cash = num(o2, "prvs_rcdl_excc_amt", "dnca_tot_amt")
    if total is None:
        total = sum(h["eval_amount"] or 0 for h in holdings) + (cash or 0)
    return {"kind": "stock", "total": total, "cash": cash, "holdings": holdings, "raw_summary": o2}


def fetch_pension(acc):
    rows, o2 = kis_get(acc, "/uapi/domestic-stock/v1/trading/pension/inquire-balance", "TTTC2208R", {
        "CANO": acc["cano"], "ACNT_PRDT_CD": acc["prdt"], "ACCA_DVSN_CD": "00", "INQR_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
    holdings = parse_holdings(rows)
    cash, dep_raw = None, {}
    try:
        dep_rows, dep_raw = kis_get(acc, "/uapi/domestic-stock/v1/trading/pension/inquire-deposit", "TTTC0506R", {
            "CANO": acc["cano"], "ACNT_PRDT_CD": acc["prdt"], "ACCA_DVSN_CD": "00"})
        dep_raw = dep_raw or (dep_rows[0] if dep_rows else {})
        cash = num(dep_raw, "dnca_tota", "dnca_tot_amt", "prvs_rcdl_excc_amt", "nxdy_excc_amt")
    except KisError as e:
        say(f"  ({acc['id']}) 예수금 조회 건너뜀: {e}")
    total = num(o2, "tot_evlu_amt", "evlu_amt_smtl", "evlu_amt_smtl_amt")
    if total is None or (cash and total == sum(h["eval_amount"] or 0 for h in holdings)):
        total = sum(h["eval_amount"] or 0 for h in holdings) + (cash or 0)
    return {"kind": "pension", "total": total, "cash": cash, "holdings": holdings, "raw_summary": {**o2, **{f"예수금.{k}": v for k, v in (dep_raw or {}).items()}}}


def fetch_account(acc):
    kind = acc.get("kind") or ("pension" if acc["prdt"] == "29" else "auto")
    if kind == "stock":
        return fetch_stock(acc)
    if kind == "pension":
        return fetch_pension(acc)
    try:
        return fetch_stock(acc)
    except KisError as e:
        say(f"  ({acc['id']}) 일반 잔고조회가 안 돼서 연금 잔고조회로 다시 시도: {e}")
        time.sleep(0.5)
        return fetch_pension(acc)


# ----------------------------------------------------------------- Supabase
def sb(method, path, body=None, prefer=None):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode())
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read().decode()
            return json.loads(t) if t.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Supabase {method} {path.split('?')[0]} 실패 (HTTP {e.code})")


def save(month, acc_id, res):
    m = f"{month}-01"
    existing = sb("GET", f"account_monthly?select=month&month=eq.{m}&account_id=eq.{acc_id}")
    if existing:
        # 이미 있으면 총액만 바꾸고, 앱에서 고친 입금액·배당금은 그대로 둠
        sb("PATCH", f"account_monthly?month=eq.{m}&account_id=eq.{acc_id}",
           {"total": round(res["total"]), "source": "한국투자증권 API", "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()},
           "return=minimal")
    else:
        # 입금액은 API 로 알 수 없어서 지난달 입금액으로 추정 → 앱에 '확인 필요' 표시
        prev = sb("GET", f"account_monthly?select=deposit&account_id=eq.{acc_id}&month=lt.{m}&order=month.desc&limit=1")
        deposit = float(prev[0]["deposit"]) if prev else 0
        sb("POST", "account_monthly", {"month": m, "account_id": acc_id, "total": round(res["total"]), "deposit": deposit,
                                       "dividend": 0, "source": "한국투자증권 API", "deposit_auto": True}, "return=minimal")
    sb("DELETE", f"holdings_monthly?month=eq.{m}&account_id=eq.{acc_id}", prefer="return=minimal")
    if res["holdings"]:
        sb("POST", "holdings_monthly", [{"month": m, "account_id": acc_id, **h} for h in res["holdings"]], "return=minimal")


# ----------------------------------------------------------------- main
def load_accounts():
    raw = os.environ.get("KIS_ACCOUNTS", "").strip()
    if not raw and os.path.exists(os.path.expanduser("~/kis_accounts.json")):
        raw = open(os.path.expanduser("~/kis_accounts.json"), encoding="utf-8").read()
    if not raw:
        sys.exit("KIS_ACCOUNTS 설정이 없어요. (맥에서는 홈 폴더의 kis_accounts.json 파일, GitHub 에서는 Secrets)")
    try:
        accs = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit("KIS_ACCOUNTS 형식이 JSON 이 아니에요. 따옴표·쉼표·대괄호를 확인해 주세요.")
    for a in accs:
        missing = [k for k in ("id", "cano", "prdt", "app_key", "app_secret") if not str(a.get(k, "")).strip()]
        if missing:
            sys.exit(f"KIS_ACCOUNTS 의 '{a.get('id', '?')}' 계좌에 {', '.join(missing)} 값이 없어요.")
        a["cano"] = str(a["cano"]).replace("-", "").strip()[:8]
        a["prdt"] = str(a["prdt"]).strip().zfill(2)
    return accs


def main():
    global QUIET
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--save", action="store_true")
    ap.add_argument("--month", help="저장할 달 YYYY-MM (기본: 지난달)")
    ap.add_argument("--force", action="store_true", help="매월 1일 장 시작 전이 아니어도 저장")
    a = ap.parse_args()
    QUIET = a.save

    now = dt.datetime.now(KST)
    if a.save and not a.force:
        # 예약 실행은 매달 말일 밤(UTC)=한국 1일 아침에 돌아요. 1일 장 시작(9시) 전에만 저장해서 월말 가격을 남겨요.
        if now.day != 1 or now.hour >= 9:
            say(f"오늘은 저장하는 날이 아니에요 (한국 시간 {now:%m-%d %H:%M}). 매월 1일 9시 전에만 저장해요. 종료.")
            return 0
    prev = (now.replace(day=1) - dt.timedelta(days=1))
    month = a.month or f"{prev:%Y-%m}"
    accs = load_accounts()
    say(f"{'저장' if a.save else '확인'}: {len(accs)}개 계좌, {month} 말 기준")

    ok, failed = 0, []
    for acc in accs:
        try:
            res = fetch_account(acc)
        except KisError as e:
            failed.append(acc["id"])
            say(f"  ✗ {acc['id']}: {e}")
            continue
        if a.check:
            say(f"\n■ {acc['id']} ({acc['prdt']}, {res['kind']} 방식)")
            cash = "알 수 없음" if res["cash"] is None else f"{res['cash']:,.0f} 원"
            say(f"  계좌 총액: {res['total']:,.0f} 원   예수금: {cash}")
            for h in res["holdings"]:
                say(f"  - {h['name']} ({h['symbol']}) {h['qty']:,.0f}주  평단 {h['avg_price'] or 0:,.0f}  "
                    f"현재가 {h['price'] or 0:,.0f}  평가 {h['eval_amount'] or 0:,.0f}")
            say("  [요약 항목 이름] " + ", ".join(sorted(k for k, v in res["raw_summary"].items() if str(v).strip() not in ("", "0", "0.00"))))
        else:
            try:
                save(month, acc["id"], res)
                ok += 1
                say(f"  ✓ {acc['id']}: 저장 (보유 종목 {len(res['holdings'])}개)")
            except RuntimeError as e:
                failed.append(acc["id"])
                say(f"  ✗ {acc['id']}: {e}")
        time.sleep(0.3)

    if a.save:
        say(f"완료: {ok}개 저장, {len(failed)}개 실패{(' (' + ', '.join(failed) + ')') if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
