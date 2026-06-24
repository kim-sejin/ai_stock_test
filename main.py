import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context(cafile=certifi.where())

import os
import smtplib
import pandas as pd
import FinanceDataReader as fdr

from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

app = FastAPI()

# ─────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────
EMAIL_SENDER   = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# ─────────────────────────────────────────
# 종목 DB (파일 없이 코드에 내장)
# ─────────────────────────────────────────
STOCKS_DB = {
  "삼성전자": "005930",
  "SK하이닉스": "000660",
  "LG에너지솔루션": "373220",
  "삼성바이오로직스": "207940",
  "현대차": "005380",
  "기아": "000270",
  "POSCO홀딩스": "005490",
  "셀트리온": "068270",
  "KB금융": "105560",
  "신한지주": "055550",
  "NAVER": "035420",
  "카카오": "035720",
  "LG화학": "051910",
  "삼성SDI": "006400",
  "현대모비스": "012330",
  "삼성물산": "028260",
  "SK이노베이션": "096770",
  "SK": "034730",
  "하나금융지주": "086790",
  "우리금융지주": "316140",
  "LG전자": "066570",
  "삼성생명": "032830",
  "두산에너빌리티": "034020",
  "에코프로비엠": "247540",
  "에코프로": "086520",
  "포스코퓨처엠": "003670",
  "카카오뱅크": "323410",
  "크래프톤": "259960",
  "엔씨소프트": "036570",
  "넷마블": "251270",
  "카카오게임즈": "293490",
  "펄어비스": "263750",
  "하이브": "352820",
  "SM": "041510",
  "JYP Ent.": "035900",
  "와이지엔터테인먼트": "122870",
  "CJ제일제당": "097950",
  "오리온": "271560",
  "농심": "004370",
  "롯데칠성": "005300",
  "아모레퍼시픽": "090430",
  "LG생활건강": "051900",
  "한국콜마": "161890",
  "코스맥스": "192820",
  "현대건설": "000720",
  "GS건설": "006360",
  "대우건설": "047040",
  "HDC현대산업개발": "294870",
  "롯데케미칼": "011170",
  "금호석유": "011780",
  "한화솔루션": "009830",
  "OCI홀딩스": "010060",
  "SK케미칼": "285130",
  "삼성전기": "009150",
  "LG이노텍": "011070",
  "삼성에스디에스": "018260",
  "SK텔레콤": "017670",
  "KT": "030200",
  "LG유플러스": "032640",
  "한국전력": "015760",
  "한국가스공사": "036460",
  "S-Oil": "010950",
  "GS": "078930",
  "HD현대": "267250",
  "한화에어로스페이스": "012450",
  "한화": "000880",
  "두산밥캣": "241560",
  "현대로템": "064350",
  "LIG넥스원": "079550",
  "한국항공우주": "047810",
  "대한항공": "003490",
  "아시아나항공": "020560",
  "제주항공": "089590",
  "HMM": "011200",
  "팬오션": "028670",
  "CJ대한통운": "000120",
  "롯데쇼핑": "023530",
  "신세계": "004170",
  "현대백화점": "069960",
  "BGF리테일": "282330",
  "GS리테일": "007070",
  "이마트": "139480",
  "카카오페이": "377300",
  "삼성증권": "016360",
  "미래에셋증권": "006800",
  "키움증권": "039490",
  "메리츠금융지주": "138040",
  "DB손해보험": "005830",
  "삼성화재": "000810",
  "현대해상": "001450",
  "한미약품": "128940",
  "유한양행": "000100",
  "종근당": "185750",
  "동아에스티": "170900",
  "셀트리온헬스케어": "091990",
  "알테오젠": "196170",
  "리가켐바이오": "141080"
}

# ─────────────────────────────────────────
# 상태 (메모리)
# ─────────────────────────────────────────
WATCHLIST = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
}

SETTINGS = {
    "alert_threshold": 3.0,
    "auto_alert": True,
}


# ─────────────────────────────────────────
# 이메일
# ─────────────────────────────────────────
def send_email(subject: str, message: str):
    try:
        msg = MIMEMultipart()
        msg["From"]    = EMAIL_SENDER
        msg["To"]      = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {e}")
        return False


# ─────────────────────────────────────────
# 종목명 → 코드 변환
# ─────────────────────────────────────────
def get_ticker_by_name(name: str) -> dict:
    # 정확히 일치
    if name in STOCKS_DB:
        return {"code": STOCKS_DB[name], "name": name}

    # 부분 일치
    matches = [
        {"Name": k, "Code": v}
        for k, v in STOCKS_DB.items()
        if name in k
    ]

    if matches:
        return {"matches": matches[:5]}

    return {"error": f"'{name}'을 찾을 수 없습니다. (약 100개 주요 종목 지원)"}


# ─────────────────────────────────────────
# 주식 가격 조회
# ─────────────────────────────────────────
def fetch_stock(ticker: str, name: str) -> dict:
    try:
        df = fdr.DataReader(ticker, datetime.today().strftime('%Y-%m-%d'))
        if df.empty:
            return {"ticker": ticker, "name": name, "error": "데이터 없음"}

        price      = int(df.iloc[-1]['Close'])
        open_price = int(df.iloc[-1]['Open'])
        change_pct = round(((price - open_price) / open_price) * 100, 2)

        return {
            "ticker":     ticker,
            "name":       name,
            "price":      price,
            "change_pct": change_pct,
            "alert":      abs(change_pct) >= SETTINGS["alert_threshold"],
        }
    except Exception as e:
        return {"ticker": ticker, "name": name, "error": str(e)}


def check_all_stocks(send_alert=True) -> list:
    results = []
    alerts  = []

    for ticker, name in WATCHLIST.items():
        result = fetch_stock(ticker, name)
        results.append(result)
        if result.get("alert") and send_alert:
            alerts.append(result)

    if alerts and SETTINGS["auto_alert"] and send_alert:
        lines = [f"⚠️ {r['name']}: {r['price']:,}원 ({r['change_pct']:+.2f}%)" for r in alerts]
        body  = "🚨 등락률 알림\n\n" + "\n".join(lines)
        send_email("🚨 주식 등락률 알림", body)

    return results


# ─────────────────────────────────────────
# 라우트
# ─────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    html = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/api/stocks")
def api_stocks():
    results = check_all_stocks(send_alert=False)
    return JSONResponse(results)


@app.post("/api/stocks/add")
async def api_add_stock(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "종목명을 입력하세요."}, status_code=400)

    result = get_ticker_by_name(name)
    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=404)
    if "matches" in result:
        return JSONResponse({"matches": result["matches"]})

    code       = result["code"]
    stock_name = result["name"]
    if code in WATCHLIST:
        return JSONResponse({"error": f"'{stock_name}'은 이미 감시 목록에 있습니다."}, status_code=409)

    WATCHLIST[code] = stock_name
    return JSONResponse({"success": True, "code": code, "name": stock_name})


@app.post("/api/stocks/remove")
async def api_remove_stock(request: Request):
    body   = await request.json()
    ticker = body.get("ticker", "").strip()
    if ticker in WATCHLIST:
        name = WATCHLIST.pop(ticker)
        return JSONResponse({"success": True, "name": name})
    return JSONResponse({"error": "종목을 찾을 수 없습니다."}, status_code=404)


@app.get("/api/settings")
def api_get_settings():
    return JSONResponse(SETTINGS)


@app.post("/api/settings")
async def api_update_settings(request: Request):
    body = await request.json()
    if "alert_threshold" in body:
        SETTINGS["alert_threshold"] = float(body["alert_threshold"])
    if "auto_alert" in body:
        SETTINGS["auto_alert"] = bool(body["auto_alert"])
    return JSONResponse({"success": True, "settings": SETTINGS})
