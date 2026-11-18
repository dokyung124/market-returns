# 종목 코드 ↔ 엑셀 헤더 이름 ↔ 원화 환산에 쓰는 환율 코드
# (앱 화면 설정은 index.html 의 ASSETS 와 같아야 해요)
ASSETS = [
    # code,      엑셀 헤더(=update_index.SOURCES 키), 원화환산 환율 코드(None=이미 원화 or 환율 자체)
    ("SPX",     "S&P 500(H)",        "USDKRW"),
    ("NASDAQ",  "나스닥(H)",          "USDKRW"),
    ("DJI",     "다우 존스(H)",       "USDKRW"),
    ("USDKRW",  "원 달러 환율",        None),
    ("KOSPI",   "코스피",             None),
    ("KOSDAQ",  "코스닥",             None),
    ("CSI300",  "차이나 CSI 300(H)",  "CNYKRW"),
    ("CSI500",  "차이나 CSI 500(H)",  "CNYKRW"),
    ("STAR50",  "과창판 STAR50(H)",   "CNYKRW"),
    ("CNYKRW",  "원 위안 환율",        None),
    ("HSI",     "항셍 지수(H)",        "HKDKRW"),
    ("HSTECH",  "항셍 테크(H)",        "HKDKRW"),
    ("HKDKRW",  "홍콩 달러 원 환율",    None),
    ("N225",    "닛케이(H)",          "JPYKRW"),
    ("JPYKRW",  "원 엔 환율",          None),
    ("NIFTY50", "인도 니프티 50(H)",   "INRKRW"),
    ("INRKRW",  "원 루피 환율",        None),
    ("SX5E",    "유로 스톡스 50(H)",   "EURKRW"),
    ("EURKRW",  "원 유로 환율",        None),
    ("VNI",     "베트남 VN (H)",       "VNDKRW"),
    ("VNDKRW",  "베트남 동 환율",       None),
    ("SET",     "태국 SET (H)",        "THBKRW"),
    ("THBKRW",  "태국 바트 환율",       None),
    ("BTC",     "비트코인(H)",         "USDKRW"),
    ("ETH",     "이더리움(H)",         "USDKRW"),
    ("XRP",     "리플(H)",            "USDKRW"),
    ("SOL",     "솔라나(H)",          "USDKRW"),
    ("GOLD",    "국제금",             "USDKRW"),
    ("KRXGOLD", "국내금",             None),
    ("SILVER",  "은",                "USDKRW"),
    ("COPPER",  "구리",               "USDKRW"),
    ("TSLA",    "테슬라(H)",          "USDKRW"),
]
CODE_BY_LABEL = {label: code for code, label, _ in ASSETS}
LABEL_BY_CODE = {code: label for code, label, _ in ASSETS}
