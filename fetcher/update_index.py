#!/usr/bin/env python3
"""
'지수 Raw Data' 시트에 지난달 월말 종가를 자동 입력하는 스크립트.

- A열 날짜가 2026-10-01 인 행  →  2026년 10월 마지막 거래일 종가
- 이미 값이 있는 칸은 절대 덮어쓰지 않음 (빈 칸만 채움)
- 수식 칸(F, G, H, O, P ...)은 건드리지 않음
- 엑셀 파일 안의 차트/서식/다른 시트는 그대로 유지 (셀 XML만 직접 수정)
- 쓰기 전에 원본을 backups 폴더에 백업

사용법
  python update_index.py --file "엑셀경로.xlsx"                 # 자동 모드 (매월 1일에 실행되는 모드)
  python update_index.py --file "엑셀경로.xlsx" --check 2026-10 # 10월 값을 받아와서 이미 입력된 값과 비교만 (파일 안 바뀜)
  python update_index.py --file "엑셀경로.xlsx" --month 2026-11 # 특정 월을 강제로 채우기 (빈 칸만)
  python update_index.py --file "엑셀경로.xlsx" --dry-run       # 무엇을 채울지 출력만
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
import logging
import warnings

warnings.filterwarnings("ignore", message=".*OpenSSL.*")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

SHEET_NAME = "지수 Raw Data"
RETRY_DAYS = 10          # 월말 후 며칠 동안 빈 칸 재시도할지 (그 뒤로는 수동 입력)
KEEP_BACKUPS = 12

# 헤더 이름 → 데이터 출처 후보 (앞에서부터 차례로 시도, 처음 성공한 값 사용)
#   ("yahoo", 티커) / ("em", 동방재부 코드) / ("cross", 야후 USD 환율 티커: KRW=X ÷ 이 값)
#   ("vnd_finfo",) ("vnd_dchart",) VNDirect / ("set_th",) 태국거래소 / ("naver_gold",) KRX 금
SOURCES = {
    "S&P 500(H)":        [("yahoo", "^GSPC")],
    "나스닥(H)":          [("yahoo", "^IXIC")],
    "다우 존스(H)":       [("yahoo", "^DJI")],
    "원 달러 환율":        [("yahoo", "KRW=X")],
    "코스피":             [("yahoo", "^KS11")],
    "코스닥":             [("yahoo", "^KQ11")],
    "차이나 CSI 300(H)":  [("yahoo", "000300.SS"), ("tencent", "sh000300"), ("sina", "sh000300"), ("em", "1.000300")],
    "차이나 CSI 500(H)":  [("yahoo", "000905.SS"), ("tencent", "sh000905"), ("sina", "sh000905"), ("em", "1.000905")],
    "과창판 STAR50(H)":   [("yahoo", "000688.SS"), ("tencent", "sh000688"), ("sina", "sh000688"), ("em", "1.000688")],
    "원 위안 환율":        [("yahoo", "CNYKRW=X"), ("cross", "CNY=X")],
    "항셍 지수(H)":        [("yahoo", "^HSI"), ("em", "100.HSI")],
    "항셍 테크(H)":        [("yahoo", "HSTECH.HK"), ("tencent", "hkHSTECH"), ("cnbc", ".HSTECH"), ("em", "124.HSTECH")],
    "홍콩 달러 원 환율":    [("yahoo", "HKDKRW=X"), ("cross", "HKD=X")],
    "닛케이(H)":          [("yahoo", "^N225")],
    "원 엔 환율":          [("yahoo", "JPYKRW=X"), ("cross", "JPY=X")],
    "인도 니프티 50(H)":   [("yahoo", "^NSEI")],
    "원 루피 환율":        [("yahoo", "INRKRW=X"), ("cross", "INR=X")],
    "유로 스톡스 50(H)":   [("yahoo", "^STOXX50E")],
    "원 유로 환율":        [("yahoo", "EURKRW=X")],
    "베트남 VN (H)":       [("yahoo", "^VNINDEX.VN"), ("em", "100.VNINDEX"), ("vnd_finfo",), ("vnd_dchart",)],
    "베트남 동 환율":       [("yahoo", "VNDKRW=X"), ("cross", "VND=X")],
    "태국 SET (H)":        [("yahoo", "^SET.BK"), ("cnbc", ".SETI"), ("stooq", "^set"),
                           ("naver_index", ".SETI"), ("em", "100.SET"), ("set_th",)],
    "태국 바트 환율":       [("yahoo", "THBKRW=X"), ("cross", "THB=X")],
    "비트코인(H)":         [("yahoo", "BTC-USD")],
    "이더리움(H)":         [("yahoo", "ETH-USD")],
    "리플(H)":            [("yahoo", "XRP-USD")],
    "솔라나(H)":          [("yahoo", "SOL-USD")],
    "국제금":             [("yahoo", "GC=F")],
    "국내금":             [("naver_gold",)],
    "은":                [("yahoo", "SI=F")],
    "구리":               [("yahoo", "HG=F")],
    "테슬라(H)":          [("yahoo", "TSLA")],
}

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def log(*a):
    print(dt.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]"), *a, flush=True)


def notify(msg: str):
    """맥 알림센터에 알림 표시 (실패해도 무시)."""
    if sys.platform != "darwin":
        return
    msg = msg.replace('"', "'")
    try:
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "월말 종가 자동입력"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass


# ---------------------------------------------------------------- 엑셀 셀 주소 도우미
def col_to_idx(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def split_ref(ref: str):
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    return m.group(1), int(m.group(2))


def serial_to_date(v: float) -> dt.date:
    return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(v)))


def month_end(y: int, m: int) -> dt.date:
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def fmt_num(v: float) -> str:
    a = abs(v)
    digits = 2 if a >= 1000 else 4 if a >= 10 else 6 if a >= 0.1 else 10
    s = repr(round(v, digits))
    return s[:-2] if s.endswith(".0") else s


# ---------------------------------------------------------------- 데이터 가져오기
def last_close_in_month(dates_closes, y, m):
    best = None
    for d, c in dates_closes:
        if d.year == y and d.month == m and c is not None and c == c:  # c==c: NaN 제외
            if best is None or d >= best[0]:
                best = (d, float(c))
    return best


# 각 출처 함수는 (start ~ end) 기간의 일별 [(날짜, 종가), ...] 를 돌려줌
def p_yahoo(sym, start, end):
    import yfinance as yf  # 설치 필요: pip install yfinance
    for attempt in range(3):
        try:
            t = yf.Ticker(sym)
            df = t.history(start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
                           interval="1d", auto_adjust=False)
            if df is None or df.empty:   # 기간 지정이 안 먹는 티커 대비
                df = t.history(period="5y", interval="1d", auto_adjust=False)
            if df is None or df.empty:
                return []
            return [(idx.date(), row["Close"]) for idx, row in df.iterrows()]
        except Exception as e:  # 일시적 오류/요청 제한 → 잠깐 쉬고 재시도
            if "not found" in str(e).lower() or "delisted" in str(e).lower():
                return []
            time.sleep(5 * (attempt + 1))
    return []


def p_cross(usd_sym, start, end):
    """원/외화 환율 = (원/달러) ÷ (외화/달러). 예: 원/위안 = KRW=X ÷ CNY=X"""
    krw = {d: c for d, c in p_yahoo("KRW=X", start, end) if c == c}
    out = []
    for d, c in p_yahoo(usd_sym, start, end):
        if d in krw and c == c and c:
            out.append((d, krw[d] / c))
    return out


def http_get(url, referer=None):
    h = dict(UA)
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def http_json(url, referer=None):
    txt = http_get(url, referer).strip()
    m = re.match(r"^[\w$]+\((.*)\);?$", txt, re.S)  # JSONP 대비
    return json.loads(m.group(1) if m else txt)


def p_em(secid, start, end):
    """동방재부(東方財富) 일봉."""
    for i, host in enumerate(("push2his.eastmoney.com", "push2his.eastmoney.com", "63.push2his.eastmoney.com")):
        if i:
            time.sleep(4 * i)
        url = (f"https://{host}/api/qt/stock/kline/get?secid={secid}"
               f"&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55&klt=101&fqt=0"
               f"&beg={start:%Y%m%d}&end={end:%Y%m%d}&lmt=100000&ut=fa5fd1943c7b386f172d6893dbfba10b")
        try:
            j = http_json(url, "https://quote.eastmoney.com/")
            kl = ((j or {}).get("data") or {}).get("klines") or []
            return [(dt.date.fromisoformat(x.split(",")[0]), float(x.split(",")[2])) for x in kl]
        except Exception as e:
            log(f"  동방재부({secid}) 오류: {e}")
    return []


def p_vnd_finfo(start, end):
    url = ("https://api-finfo.vndirect.com.vn/v4/vnmarket_prices?sort=date&size=2000&page=1"
           f"&q=code:VNINDEX~date:gte:{start}~date:lte:{end}")
    try:
        j = http_json(url, "https://dstock.vndirect.com.vn/")
        return [(dt.date.fromisoformat(d["date"][:10]), float(d["close"])) for d in j.get("data", [])]
    except Exception as e:
        log(f"  VNDirect(finfo) 오류: {e}")
    return []


def p_vnd_dchart(start, end):
    t0 = int(dt.datetime.combine(start, dt.time()).timestamp())
    t1 = int(dt.datetime.combine(end, dt.time(23, 59)).timestamp())
    url = f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol=VNINDEX&from={t0}&to={t1}"
    try:
        j = http_json(url, "https://dchart.vndirect.com.vn/")
        vn_tz = dt.timezone(dt.timedelta(hours=7))
        return [(dt.datetime.fromtimestamp(t, vn_tz).date(), c) for t, c in zip(j.get("t", []), j.get("c", []))]
    except Exception as e:
        log(f"  VNDirect(차트) 오류: {e}")
    return []


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _parse_date(s):
    m = re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(s))
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


DATE_KEYS = ("localTradedAt", "tradedAt", "date", "datetime", "localDatetime", "tradeDate", "tradingDate",
             "day", "tradeTime")
PRICE_KEYS = ("closePrice", "close", "closingPrice", "price", "last")


def _pairs_from_json(j):
    pairs = []
    for d in _walk(j):
        dk = next((k for k in DATE_KEYS if k in d), None)
        ck = next((k for k in PRICE_KEYS if k in d), None)
        if dk and ck:
            day = _parse_date(d[dk])
            try:
                price = float(str(d[ck]).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if day:
                pairs.append((day, price))
    return pairs


def _is_daily(pairs):
    """주봉/월봉 데이터는 월말 종가가 틀릴 수 있어서 일봉만 사용."""
    ds = sorted({d for d, _ in pairs})
    if len(ds) < 5:
        return bool(ds)
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    return gaps[len(gaps) // 2] <= 3


def p_set_th(start, end):
    """태국 SET 지수: 태국거래소 공식 사이트."""
    out = []
    for period in ("5Y", "1Y", "3M"):
        url = f"https://www.set.or.th/api/set/index/SET/chart-quotation?period={period}&accumulated=false"
        try:
            pairs = _pairs_from_json(http_json(url, "https://www.set.or.th/en/market/index/set/overview"))
            if _is_daily(pairs):
                out += pairs
        except Exception as e:
            log(f"  태국거래소 오류: {e}")
            break
    return out


def _naver_paged(url_tpl, start, referer=None, label="네이버"):
    out = []
    for p in range(1, 40):
        pairs = _pairs_from_json(http_json(url_tpl.format(p=p), referer))
        if not pairs:
            break
        out += pairs
        if min(d for d, _ in pairs) < start:
            break
        time.sleep(0.2)
    return out


def p_naver_gold(start, end):
    """국내금(KRX 금시장, 원/g): 네이버 증권."""
    urls = [
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page={p}&pageSize=60",
        "https://api.stock.naver.com/marketindex/metals/M04020000/prices?page={p}&pageSize=60",
    ]
    for u in urls:
        try:
            out = _naver_paged(u, start)
            if out:
                return out
        except Exception as e:
            log(f"  네이버 금시세 오류: {e}")
    return []


def p_naver_index(code, start, end):
    urls = [
        "https://api.stock.naver.com/index/" + code + "/price?page={p}&pageSize=60",
        "https://m.stock.naver.com/front-api/index/" + code + "/price?page={p}&pageSize=60",
    ]
    for u in urls:
        try:
            out = _naver_paged(u, start, "https://m.stock.naver.com/")
            if out:
                return out
        except Exception as e:
            log(f"  네이버({code}) 오류: {e}")
    return []


def p_stooq(sym, start, end):
    url = f"https://stooq.com/q/d/l/?s={urllib.request.quote(sym)}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
    try:
        out = []
        for line in http_get(url).splitlines()[1:]:
            p = line.split(",")
            if len(p) >= 5:
                try:
                    out.append((dt.date.fromisoformat(p[0]), float(p[4])))
                except ValueError:
                    pass
        if not out:
            log(f"  stooq({sym}) 데이터 없음")
        return out
    except Exception as e:
        log(f"  stooq({sym}) 오류: {e}")
    return []


def p_tencent(code, start, end):
    """텐센트 증권 일봉 (중국 지수 sh000300 / 홍콩 지수 hkHSTECH 등). 기간이 길면 나눠서 요청."""
    out = []
    s = start
    while s <= end:
        e = min(end, s + dt.timedelta(days=360))
        got = False
        for host in ("web.ifzq.gtimg.cn", "proxy.finance.qq.com/ifzqgtimg"):
            url = f"https://{host}/appstock/app/fqkline/get?param={code},day,{s},{e},640,qfq"
            try:
                j = http_json(url, "https://gu.qq.com/")
                node = ((j or {}).get("data") or {}).get(code) or {}
                rows = node.get("day") or node.get("qfqday") or []
                out += [(dt.date.fromisoformat(r[0]), float(r[2])) for r in rows if len(r) > 2]
                got = True
                break
            except Exception as ex:
                log(f"  텐센트({code}) 오류: {ex}")
        if not got:
            break
        s = e + dt.timedelta(days=1)
        time.sleep(0.3)
    return out


def p_sina(code, start, end):
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
           f"?symbol={code}&scale=240&ma=no&datalen=1023")
    try:
        return _pairs_from_json(http_json(url, "https://finance.sina.com.cn/"))
    except Exception as e:
        log(f"  시나({code}) 오류: {e}")
    return []


def p_cnbc(sym, start, end):
    """CNBC 차트 데이터. 일봉인 구간만 사용."""
    out = {}
    for rng in ("5Y", "1Y", "3M"):
        url = f"https://ts-api.cnbc.com/harmony/app/charts/{rng}.json?symbol={urllib.request.quote(sym)}"
        try:
            pairs = _pairs_from_json(http_json(url, "https://www.cnbc.com/"))
            if _is_daily(pairs):
                out.update(dict(pairs))
        except Exception as e:
            log(f"  CNBC({sym}) 오류: {e}")
            break
    return sorted(out.items())


PAIR_FUNCS = {
    "yahoo": p_yahoo, "cross": p_cross, "em": p_em,
    "vnd_finfo": p_vnd_finfo, "vnd_dchart": p_vnd_dchart,
    "set_th": p_set_th, "naver_gold": p_naver_gold,
    "naver_index": p_naver_index, "stooq": p_stooq,
    "tencent": p_tencent, "sina": p_sina, "cnbc": p_cnbc,
}
SRC_NAMES = {"yahoo": "야후", "cross": "야후 KRW=X÷", "em": "동방재부", "vnd_finfo": "VNDirect",
             "vnd_dchart": "VNDirect차트", "set_th": "태국거래소", "naver_gold": "네이버 KRX금",
             "naver_index": "네이버", "stooq": "stooq", "tencent": "텐센트", "sina": "시나", "cnbc": "CNBC"}


def fetch_months(label, months):
    """{(연, 월): (값, 출처설명)} — 출처 후보를 차례로 시도해서 빈 달을 채움."""
    months = sorted(set(months))
    if not months:
        return {}
    start = dt.date(*months[0], 1) - dt.timedelta(days=7)
    end = month_end(*months[-1])
    res = {}
    for src in SOURCES[label]:
        todo = [ym for ym in months if ym not in res]
        if not todo:
            break
        pairs = PAIR_FUNCS[src[0]](*src[1:], start, end)
        for ym in todo:
            hit = last_close_in_month(pairs, *ym)
            # 월말에서 10일 넘게 떨어진 날짜는 데이터 누락으로 보고 버림
            if hit and (month_end(*ym) - hit[0]).days <= 10:
                res[ym] = (hit[1], f"{SRC_NAMES[src[0]]}{' '.join(src[1:])} {hit[0]}")
    return res


def fetch(label, y, m):
    return fetch_months(label, [(y, m)]).get((y, m), (None, None))


# ---------------------------------------------------------------- xlsx 읽기/쓰기
class Workbook:
    def __init__(self, path: Path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.names = z.namelist()
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rid = None
            for s in wb.find("m:sheets", NS):
                if s.get("name") == SHEET_NAME:
                    rid = s.get(f"{{{NS['r']}}}id")
            if rid is None:
                raise SystemExit(f"'{SHEET_NAME}' 시트를 찾을 수 없어요.")
            target = next(r.get("Target") for r in rels if r.get("Id") == rid)
            self.sheet_part = "xl/" + target.lstrip("/").removeprefix("xl/")
            pr = wb.find("m:workbookPr", NS)
            if pr is not None and pr.get("date1904") in ("1", "true"):
                raise SystemExit("1904 날짜 체계 파일은 지원하지 않아요.")
            self.shared = []
            if "xl/sharedStrings.xml" in self.names:
                sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in sst.findall("m:si", NS):
                    self.shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
            self.sheet_xml = z.read(self.sheet_part).decode("utf-8")
            self.workbook_xml = z.read("xl/workbook.xml").decode("utf-8")

    # 행 XML 조각들
    def rows(self):
        for m in re.finditer(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', self.sheet_xml, re.S):
            yield int(m.group(1)), m

    @staticmethod
    def cells(row_xml):
        out = {}
        for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', row_xml, re.S):
            out[split_ref(m.group(1))[0]] = m
        return out

    def cell_text(self, cm):
        if cm is None or cm.group(3) is None:
            return None
        v = re.search(r"<v>(.*?)</v>", cm.group(3), re.S)
        if v is None:
            t = re.search(r"<t[^>]*>(.*?)</t>", cm.group(3), re.S)
            return t.group(1) if t else None
        if 't="s"' in cm.group(2):
            return self.shared[int(v.group(1))]
        return v.group(1)

    def header_map(self):
        for rn, m in self.rows():
            if rn == 1:
                hdr = {}
                for col, cm in self.cells(m.group(0)).items():
                    txt = self.cell_text(cm)
                    if txt:
                        hdr[txt.strip()] = col
                return hdr
        return {}

    def month_rows(self):
        """{(연, 월): (행번호, {열: 값 or None})}"""
        res = {}
        for rn, m in self.rows():
            if rn == 1:
                continue
            cells = self.cells(m.group(0))
            a = self.cell_text(cells.get("A"))
            try:
                d = serial_to_date(float(a))
            except (TypeError, ValueError):
                continue
            vals = {col: self.cell_text(cm) for col, cm in cells.items()}
            res[(d.year, d.month)] = (rn, vals)
        return res

    def prev_style(self, col, rn):
        """같은 열 윗행의 서식 번호 (새 셀 만들 때 사용)."""
        for r2, m in self.rows():
            if r2 == rn - 1:
                cm = self.cells(m.group(0)).get(col)
                if cm:
                    s = re.search(r'\ss="(\d+)"', cm.group(2))
                    return s.group(1) if s else None
        return None

    def set_values(self, rn, values: dict, overwrite=False):
        """values: {열: 숫자}. 기본은 빈 칸에만 기록, overwrite=True 면 숫자 칸도 덮어씀 (수식·글자 칸은 절대 안 건드림)."""
        m = next(m for r, m in self.rows() if r == rn)
        row_xml = m.group(0)
        if row_xml.endswith("/>"):
            open_tag, body = row_xml[:-2] + ">", ""
        else:
            open_tag = row_xml[: row_xml.index(">") + 1]
            body = row_xml[len(open_tag): -len("</row>")]
        cells = list(re.finditer(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', body, re.S))
        pieces = [(col_to_idx(c.group(1)), c.group(0)) for c in cells]
        existing = {c.group(1): c for c in cells}
        for col, val in values.items():
            num = fmt_num(val)
            if col in existing:
                c = existing[col]
                inner = c.group(3) or ""
                if re.search(r"<(f|is)\b", inner) or re.search(r'\st="(s|str|inlineStr)"', c.group(2)):
                    continue  # 수식·글자 칸은 건드리지 않음
                if "<v>" in inner and not overwrite:
                    continue  # 값이 이미 있으면 건드리지 않음
                attrs = re.sub(r'\st="[^"]*"', "", c.group(2))
                new = f'<c r="{col}{rn}"{attrs}><v>{num}</v></c>'
                pieces = [(i, new if p == c.group(0) else p) for i, p in pieces]
            else:
                s = self.prev_style(col, rn)
                sattr = f' s="{s}"' if s else ""
                pieces.append((col_to_idx(col), f'<c r="{col}{rn}"{sattr}><v>{num}</v></c>'))
        pieces.sort(key=lambda x: x[0])
        new_row = open_tag + "".join(p for _, p in pieces) + "</row>"
        self.sheet_xml = self.sheet_xml[: m.start()] + new_row + self.sheet_xml[m.end():]

    def save(self):
        # 엑셀이 열 때 전체 재계산하도록 설정
        wb_xml = self.workbook_xml
        if re.search(r"<calcPr\b", wb_xml):
            if "fullCalcOnLoad" not in re.search(r"<calcPr\b[^>]*>", wb_xml).group(0):
                wb_xml = re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', wb_xml, count=1)
        else:
            wb_xml = wb_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')

        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(self.path, backup_dir / f"{self.path.stem}_{stamp}{self.path.suffix}")
        olds = sorted(backup_dir.glob(f"{self.path.stem}_*{self.path.suffix}"))
        for old in olds[:-KEEP_BACKUPS]:
            old.unlink()

        tmp = self.path.with_name(self.path.name + ".tmp")
        with zipfile.ZipFile(self.path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == self.sheet_part:
                    data = self.sheet_xml.encode("utf-8")
                elif info.filename == "xl/workbook.xml":
                    data = wb_xml.encode("utf-8")
                dst.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        tmp.replace(self.path)


def excel_is_open(path: Path) -> bool:
    d = path.parent
    return (d / f"~${path.name}").exists() or (d / f"~${path.name[2:]}").exists()


# ---------------------------------------------------------------- 메인
def parse_ym(text):
    y, m = text.split("-")
    return int(y), int(m)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--month", help="YYYY-MM 한 달만 채우기 (빈 칸만)")
    ap.add_argument("--check", help="YYYY-MM: 받아온 값과 기존 값 비교만 (파일 안 바뀜)")
    ap.add_argument("--from", dest="ym_from", help="YYYY-MM 여러 달 한꺼번에: 시작 달")
    ap.add_argument("--to", dest="ym_to", help="YYYY-MM 여러 달 한꺼번에: 끝 달")
    ap.add_argument("--overwrite", action="store_true", help="이미 있는 숫자도 받아온 값으로 덮어쓰기")
    ap.add_argument("--force", action="store_true", help="20%% 넘게 차이 나는 값도 덮어쓰기")
    ap.add_argument("--dry-run", action="store_true", help="바뀔 내용만 보여주고 파일은 그대로")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.exists():
        log(f"파일이 없어요: {path}")
        notify("엑셀 파일을 찾지 못했어요")
        sys.exit(1)

    wb = Workbook(path)
    hdr = wb.header_map()
    cols = {}
    for label in SOURCES:
        if label in hdr:
            cols[label] = hdr[label]
        else:
            log(f"경고: 헤더 '{label}' 열을 못 찾아서 건너뜀")
    rows = wb.month_rows()
    today = dt.date.today()

    # ---- 비교 모드
    if args.check:
        ym = parse_ym(args.check)
        if ym not in rows:
            raise SystemExit(f"{args.check} 행이 없어요.")
        rn, vals = rows[ym]
        print(f"\n{args.check} (엑셀 {rn}행) 비교 — 엑셀값 / 받아온값 / 차이")
        for label, col in cols.items():
            v, src = fetch(label, *ym)
            cur = to_float(vals.get(col))
            diff = f"{(v / cur - 1) * 100:+.2f}%" if (v is not None and cur) else ""
            print(f"  {col:>3} {label:<14} {('' if cur is None else fmt_num(cur)):>14} / "
                  f"{('없음' if v is None else fmt_num(v)):>14}  {diff:>8}  {src or ''}")
        return

    # ---- 채울 달 정하기
    overwrite = args.overwrite
    if args.ym_from or args.ym_to:
        lo = parse_ym(args.ym_from or args.ym_to)
        hi = parse_ym(args.ym_to or args.ym_from)
        targets = [ym for ym in rows if lo <= ym <= hi]
    elif args.month:
        targets = [parse_ym(args.month)]
    else:  # 자동 모드: 끝난 지 RETRY_DAYS 일 안 된 달의 빈 칸만
        targets = [ym for ym in rows
                   if month_end(*ym) < today and (today - month_end(*ym)).days <= RETRY_DAYS]
    targets = [ym for ym in sorted(targets) if ym in rows and month_end(*ym) < today]
    if not targets:
        log("채울 달이 없어요. 종료.")
        return

    need = {}  # label -> 받아올 달 목록
    for ym in targets:
        rn, vals = rows[ym]
        for label, col in cols.items():
            if overwrite or vals.get(col) in (None, ""):
                need.setdefault(label, []).append(ym)
    if not need:
        log("채울 빈 칸이 없어요. 종료.")
        return

    if excel_is_open(path) and not args.dry_run:
        log("엑셀에서 파일이 열려 있어서 이번엔 건너뜀 (다음 실행 때 다시 시도)")
        notify("엑셀 파일이 열려 있어 종가 입력을 미뤘어요. 파일을 닫아두면 다음에 자동 입력돼요.")
        return

    span = f"{targets[0][0]}-{targets[0][1]:02d} ~ {targets[-1][0]}-{targets[-1][1]:02d}"
    log(f"{span} ({len(targets)}개월) 시세 받아오는 중... {'[덮어쓰기]' if overwrite else '[빈 칸만]'}")
    got = {}
    for label, months in need.items():
        got[label] = fetch_months(label, months)
        log(f"  {label:<14} {len(got[label])}/{len(months)}개월")
        time.sleep(0.3)

    report, missing, big = [], [], []
    written = 0
    for ym in targets:
        rn, vals = rows[ym]
        to_write = {}
        for label in need:
            if ym not in need[label]:
                continue
            col = cols[label]
            old = to_float(vals.get(col))
            if ym not in got[label]:
                missing.append(f"{ym[0]}-{ym[1]:02d} {label}")
                continue
            new, src = got[label][ym]
            if old is not None and abs(new - old) <= abs(old) * 1e-9:
                continue  # 같은 값
            diff = (new / old - 1) * 100 if old else None
            status = "입력"
            if diff is not None and abs(diff) > 20 and not args.force:
                status = "보류(20%↑ 차이)"
                big.append(f"{ym[0]}-{ym[1]:02d} {label} {fmt_num(old)}→{fmt_num(new)} ({diff:+.1f}%)")
            else:
                to_write[col] = new
            report.append([f"{ym[0]}-{ym[1]:02d}", f"{col}{rn}", label,
                           "" if old is None else fmt_num(old), fmt_num(new),
                           "" if diff is None else f"{diff:+.2f}%", src, status])
        if to_write and not args.dry_run:
            wb.set_values(rn, to_write, overwrite=overwrite)
        written += len(to_write)

    if len(report) <= 40:
        for r in report:
            print("   " + " | ".join(r))

    if args.dry_run:
        log(f"dry-run: {written}칸이 바뀔 예정이에요. 파일은 그대로예요.")
    elif written:
        if excel_is_open(path):  # 받아오는 사이에 열렸으면 포기
            log("그 사이 엑셀이 열려서 저장하지 않음 (다음 실행 때 다시 시도)")
            return
        wb.save()
        log(f"저장 완료: {written}칸 입력")
    else:
        log("바뀐 칸이 없어요.")

    if report and (overwrite or len(targets) > 1):
        import csv
        out = path.parent / "backups" / f"변경내역_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
        out.parent.mkdir(exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["월", "셀", "항목", "기존값", "새값", "차이", "출처", "처리"])
            w.writerows(report)
        log(f"변경 내역: {out}")
    if big:
        more = f" 외 {len(big) - 10}칸" if len(big) > 10 else ""
        log(f"20% 넘게 차이 나서 보류한 칸 {len(big)}개 (변경내역 파일 참고, 확인 후 --force 로 덮어쓸 수 있어요): "
            + ", ".join(big[:10]) + more)
    if missing:
        more = f" 외 {len(missing) - 15}칸" if len(missing) > 15 else ""
        log(f"못 가져온 칸 {len(missing)}개 (기존 값 유지): " + ", ".join(missing[:15]) + more)

    if not args.dry_run:
        msg = f"{written}칸 입력 완료"
        if missing:
            msg += f" / 못 가져온 {len(missing)}칸"
        notify(msg)


if __name__ == "__main__":
    main()
