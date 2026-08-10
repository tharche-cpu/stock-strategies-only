"""夜盤盤前快報

早上排程（台灣 08:00，夜盤 05:00 收完、開盤 09:00 前）讀昨晚台指期夜盤
+ 昨日選股訊號，推播今日開盤方向預判與個股順風/逆風對照。

執行: uv run python premarket.py
"""

import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from stock_strategies.night_session import get_night_session
from stock_strategies.sheet import read_latest_signals
from stock_strategies.notify import send_telegram, format_premarket
from stock_strategies.twstock_source import get_realtime_quotes


REQUIRED_ENV = [
    "FINMIND_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GOOGLE_SHEET_ID",
    "GOOGLE_CREDS_JSON",
]


def _missing_env() -> list[str]:
    """GOOGLE_CREDS 接受 JSON 字串或檔案路徑任一即可。"""
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if "GOOGLE_CREDS_JSON" in missing and os.environ.get("GOOGLE_CREDS_FILE"):
        missing.remove("GOOGLE_CREDS_JSON")
    return missing


def main():
    missing = _missing_env()
    if missing:
        print(f"❌ 缺少環境變數: {missing}", file=sys.stderr)
        sys.exit(1)

    # 1. 取得台指期夜盤
    print(f"[{datetime.now()}] 取得台指期夜盤...")
    night = get_night_session()
    if night:
        print(f"  → {night['date']} 夜盤 {night['pct']:+.2f}% ({night['label']})")
    else:
        print("  → 夜盤資料暫時取不到")

    # 2. 讀昨日訊號（沿用 14:30 排程寫進 Signals 分頁的結果）
    #    讀 300 筆以涵蓋多日（單日掃描可能就數十筆 SKIP），
    #    format_premarket 會自動挑「最近一批有 BUY/WATCH」的日期。
    print("讀取昨日訊號...")
    try:
        signals = read_latest_signals(limit=300)
    except Exception as e:
        print(f"⚠️ 讀取訊號失敗: {e}", file=sys.stderr)
        signals = []
    print(f"  → {len(signals)} 筆")

    # 2b. 抓 BUY/WATCH 個股的即時報價（twstock 直連證交所，盤前參考用）
    quotes = {}
    actionable_ids = sorted({
        str(s.get("stock_id", "")).strip()
        for s in signals
        if str(s.get("action", "")).upper() in ("BUY", "WATCH")
    })
    if actionable_ids:
        print("取得即時報價...")
        quotes = get_realtime_quotes(actionable_ids)
        print(f"  → {len(quotes)} 檔有報價")
    else:
        print("  → 無 BUY/WATCH 訊號，跳過即時報價")

    # 3. 發送 Telegram 盤前快報
    print("發送 Telegram 盤前快報...")
    send_telegram(format_premarket(night, signals, quotes))
    print("✅ 完成")


if __name__ == "__main__":
    main()
