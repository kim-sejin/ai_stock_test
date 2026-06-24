import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context(cafile=certifi.where())

import anthropic
import os
import smtplib
import schedule
import time
import threading
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# ─────────────────────────────────────────
# 환경변수 로드
# ─────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EMAIL_SENDER   = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
WATCHLIST = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
}

ALERT_THRESHOLD = 3.0  # 등락률 알림 기준 (%)

_stock_list = None  # 전체 종목 리스트 캐시


# ─────────────────────────────────────────
# 이메일 알림 함수
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
        print(f"✅ 이메일 전송 완료: {subject}")
    except Exception as e:
        print(f"❌ 이메일 전송 실패: {e}")


# ─────────────────────────────────────────
# 종목명 → 코드 변환
# ─────────────────────────────────────────
def get_ticker_by_name(name: str) -> dict:
    global _stock_list
    if _stock_list is None:
        print("📋 전체 종목 리스트 로딩 중...")
        kospi  = fdr.StockListing('KOSPI')[['Code', 'Name']]
        kosdaq = fdr.StockListing('KOSDAQ')[['Code', 'Name']]
        _stock_list = pd.concat([kospi, kosdaq], ignore_index=True)

    # 정확히 일치하는 종목 먼저
    exact = _stock_list[_stock_list['Name'] == name]
    if not exact.empty:
        return {"code": exact.iloc[0]['Code'], "name": exact.iloc[0]['Name']}

    # 부분 일치 검색
    partial = _stock_list[_stock_list['Name'].str.contains(name, na=False)]
    if not partial.empty:
        matches = partial[['Code', 'Name']].head(5).to_dict('records')
        return {"matches": matches}

    return {"error": f"'{name}'에 해당하는 종목을 찾을 수 없습니다."}


# ─────────────────────────────────────────
# 도구 정의
# ─────────────────────────────────────────
tools = [
    {
        "name": "get_stock_price",
        "description": "한국 주식의 현재 가격과 등락률을 조회합니다. 종목 코드(6자리)를 입력하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "종목 코드. 예: '005930' (삼성전자), '000660' (SK하이닉스)"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "send_alert",
        "description": "이메일로 주식 알림 메시지를 전송합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "이메일 제목"
                },
                "message": {
                    "type": "string",
                    "description": "전송할 알림 메시지"
                }
            },
            "required": ["subject", "message"]
        }
    },
    {
        "name": "check_all_stocks",
        "description": "감시 목록의 모든 종목 가격을 한번에 조회하고, 등락률이 기준치를 넘으면 이메일 알림을 보냅니다.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "add_stock_by_name",
        "description": "종목명으로 감시 목록에 주식을 추가합니다. 종목 코드를 몰라도 됩니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "추가할 종목명. 예: '카카오', '현대차', 'NAVER'"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "remove_stock",
        "description": "감시 목록에서 종목을 제거합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "제거할 종목명. 예: '카카오', '삼성전자'"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "show_watchlist",
        "description": "현재 감시 목록을 보여줍니다.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# ─────────────────────────────────────────
# 도구 실행 함수
# ─────────────────────────────────────────
def get_stock_price(ticker: str) -> str:
    try:
        df = fdr.DataReader(ticker, datetime.today().strftime('%Y-%m-%d'))
        if df.empty:
            return f"❌ {ticker} 데이터를 가져올 수 없습니다. (장 마감 후이거나 잘못된 코드)"

        latest     = df.iloc[-1]
        price      = int(latest['Close'])
        open_price = int(latest['Open'])
        change_pct = ((price - open_price) / open_price) * 100
        arrow      = "🔺" if change_pct > 0 else "🔻" if change_pct < 0 else "➡️"
        name       = WATCHLIST.get(ticker, ticker)

        return (
            f"{arrow} {name} ({ticker})\n"
            f"현재가: {price:,}원\n"
            f"등락률: {change_pct:+.2f}%"
        )
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


def check_all_stocks() -> str:
    if not WATCHLIST:
        return "감시 목록이 비어 있습니다."

    results = []
    alerts  = []

    for ticker, name in WATCHLIST.items():
        try:
            df = fdr.DataReader(ticker, datetime.today().strftime('%Y-%m-%d'))
            if df.empty:
                results.append(f"⚠️ {name}: 데이터 없음")
                continue

            price      = int(df.iloc[-1]['Close'])
            open_price = int(df.iloc[-1]['Open'])
            change_pct = ((price - open_price) / open_price) * 100
            arrow      = "🔺" if change_pct > 0 else "🔻" if change_pct < 0 else "➡️"

            results.append(f"{arrow} {name}: {price:,}원 ({change_pct:+.2f}%)")

            if abs(change_pct) >= ALERT_THRESHOLD:
                alerts.append(f"⚠️ {name} 등락률 {change_pct:+.2f}% 발생!")
        except Exception as e:
            results.append(f"❌ {name}: 오류 ({e})")

    summary = "\n".join(results)

    if alerts:
        alert_body = "🚨 등락률 알림\n\n" + "\n".join(alerts) + "\n\n" + summary
        send_email("🚨 주식 등락률 알림", alert_body)
        return summary + f"\n\n✅ 이메일 알림 전송 완료 ({len(alerts)}건)"

    return summary + f"\n\n알림 기준 미달 (±{ALERT_THRESHOLD}% 미만)"


def add_stock_by_name(name: str) -> str:
    result = get_ticker_by_name(name)

    if "error" in result:
        return result["error"]

    elif "matches" in result:
        options = "\n".join([f"  - {m['Name']} ({m['Code']})" for m in result["matches"]])
        return f"'{name}' 검색 결과 여러 종목이 있습니다:\n{options}\n\n정확한 종목명을 다시 입력해주세요."

    else:
        code       = result["code"]
        stock_name = result["name"]
        if code in WATCHLIST:
            return f"'{stock_name}'은 이미 감시 목록에 있습니다."
        WATCHLIST[code] = stock_name
        return f"✅ '{stock_name}' ({code}) 감시 목록에 추가했습니다!\n현재 감시 종목: {', '.join(WATCHLIST.values())}"


def remove_stock(name: str) -> str:
    for code, stock_name in list(WATCHLIST.items()):
        if stock_name == name or name in stock_name:
            del WATCHLIST[code]
            return f"✅ '{stock_name}' ({code}) 감시 목록에서 제거했습니다.\n현재 감시 종목: {', '.join(WATCHLIST.values()) or '없음'}"
    return f"'{name}'을 감시 목록에서 찾을 수 없습니다."


def show_watchlist() -> str:
    if not WATCHLIST:
        return "감시 목록이 비어 있습니다."
    items = [f"  - {name} ({code})" for code, name in WATCHLIST.items()]
    return "📋 현재 감시 목록:\n" + "\n".join(items)


def execute_tool(name: str, inputs: dict) -> str:
    if name == "get_stock_price":
        return get_stock_price(inputs["ticker"])
    elif name == "send_alert":
        send_email(inputs.get("subject", "주식 알림"), inputs["message"])
        return "✅ 이메일 알림 전송 완료"
    elif name == "check_all_stocks":
        return check_all_stocks()
    elif name == "add_stock_by_name":
        return add_stock_by_name(inputs["name"])
    elif name == "remove_stock":
        return remove_stock(inputs["name"])
    elif name == "show_watchlist":
        return show_watchlist()
    return "❌ 알 수 없는 도구"


# ─────────────────────────────────────────
# 에이전틱 루프
# ─────────────────────────────────────────
def run_agent(user_message: str):
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=(
                "당신은 한국 주식 가격을 추적하는 AI 에이전트입니다. "
                "사용자의 요청에 따라 주식 가격을 조회하고, "
                f"등락률이 ±{ALERT_THRESHOLD}% 이상이면 이메일로 알림을 보냅니다. "
                "종목명으로 종목을 추가하거나 제거할 수 있습니다."
            ),
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\n🤖 {block.text}")
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\n🔧 도구 실행: {block.name}")
                result = execute_tool(block.name, block.input)
                print(f"📊 결과:\n{result}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# ─────────────────────────────────────────
# 주기적 자동 체크 (1분마다 백그라운드)
# ─────────────────────────────────────────
def scheduled_check():
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 자동 점검 중...")
    run_agent("모든 종목 가격을 확인하고 등락률 기준 초과 시 이메일 알림을 보내줘")


def start_scheduler():
    """백그라운드에서 1분마다 독립적으로 실행"""
    schedule.every(1).minutes.do(scheduled_check)
    while True:
        schedule.run_pending()
        time.sleep(1)


# ─────────────────────────────────────────
# 실행
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 40)
    print("📈 주식 알림 에이전트 시작!")
    print(f"감시 종목: {', '.join(WATCHLIST.values())}")
    print(f"알림 기준: ±{ALERT_THRESHOLD}%")
    print("=" * 40)
    print("명령 예시:")
    print("  카카오 추가해줘")
    print("  삼성전자 가격 알려줘")
    print("  감시 목록 보여줘")
    print("  전체 조회해줘")
    print("  종료  ← 프로그램 종료")
    print("=" * 40)

    # 스케줄러를 백그라운드 스레드로 실행
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()

    while True:
        user_input = input("\n💬 명령: ").strip()
        if user_input == "종료":
            print("에이전트를 종료합니다.")
            break
        if user_input:
            run_agent(user_input)
