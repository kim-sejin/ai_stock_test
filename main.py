import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context(cafile=certifi.where())

import os
import json
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
# 종목 DB 로드 (stocks_db.json)
# ─────────────────────────────────────────
_db_path = Path(__file__).parent / "stocks_db.json"
with open(_db_path, encoding="utf-8") as f:
    STOCKS_DB = json.load(f)  # {"삼성전자": "005930", ...}

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
# 종목명 → 코드 변환 (로컬 DB 사용)
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

    return {"error": f"'{name}'에 해당하는 종목을 찾을 수 없습니다.\n(현재 약 100개 주요 종목 지원)"}


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
