"""籌碼日報

盤後（建議 15:30 後）讀 watchlist 每檔的三大法人買賣超 + 融資融券，
推播一則籌碼摘要到 Telegram。資料來源：證交所官網（twchips 套件）。

執行: uv run python chips_report.py
"""

import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from stock_strategies.sheet import read_watchlist
from stock_strategies.chips import chip_snapshot
from stock_strategies.notify import send_telegram


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


def _fmt_signed(v) -> str:
    try:
        return f"{float(v):+,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def format_chip_report(watchlist: list[dict]) -> str:
    today = datetime.now()
    wd = "一二三四五六日"[today.weekday()]
    lines = [f"🧲 *籌碼日報* {today.strftime('%Y/%m/%d')} (週{wd})", ""]

    data_dates = set()
    blocks = []
    for row in watchlist:
        sid = str(row["stock_id"])
        name = row.get("name", "")
        snap = chip_snapshot(sid)
        if snap.get("date"):
            data_dates.add(snap["date"])

        score = snap.get("score")
        if score is None:
            blocks.append(f"• *{sid} {name}* — {snap.get('note', '籌碼資料缺')}")
            continue

        lines_block = [f"🔵 *{sid} {name}*  籌碼 {score} 分"]
        parts = []
        if snap.get("total_net") is not None:
            parts.append(f"法人 {_fmt_signed(snap['total_net'])}")
        if snap.get("foreign_net") is not None:
            parts.append(f"外資 {_fmt_signed(snap['foreign_net'])}")
        if snap.get("trust_net") is not None:
            parts.append(f"投信 {_fmt_signed(snap['trust_net'])}")
        if snap.get("dealer_net") is not None:
            parts.append(f"自營 {_fmt_signed(snap['dealer_net'])}")
        lines_block.append(" | ".join(parts))

        if snap.get("margin_balance") is not None:
            mg = snap["margin_balance"]
            mc = snap.get("margin_chg", 0)
            sc = snap.get("short_chg", 0)
            sign_m = "+" if mc > 0 else ""
            sign_s = "+" if sc > 0 else ""
            lines_block.append(
                f"融資 {mg:,.0f} ({sign_m}{mc:,.0f}) | "
                f"融券 {snap.get('short_balance', 0):,.0f} ({sign_s}{sc:,.0f})"
            )
        blocks.append("\n".join(lines_block))

    if not blocks:
        lines.append("_今日無可用籌碼資料（交易所可能尚未公布或改版）_")
    else:
        lines.extend(blocks)

    lines.append("")
    if data_dates:
        lines.append(f"📅 資料日：{', '.join(sorted(data_dates))}")
    lines.append("💡 _三大法人買賣超單位為股、融資融券為張（證交所）_")
    return "\n".join(lines)


def main():
    missing = _missing_env()
    if missing:
        print(f"❌ 缺少環境變數: {missing}", file=sys.stderr)
        sys.exit(1)

    print(f"[{datetime.now()}] 讀取 watchlist...")
    watchlist = read_watchlist()
    print(f"  → {len(watchlist)} 檔啟用中")

    print("抓取籌碼資料（法人 + 融資融券）...")
    msg = format_chip_report(watchlist)

    print("發送 Telegram...")
    send_telegram(msg)
    print("✅ 完成")


if __name__ == "__main__":
    main()
