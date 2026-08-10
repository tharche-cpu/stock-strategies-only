"""twstock 資料層：FinMind 掛掉時的備援股價源 + 即時報價 + 代碼/名稱對照。

- 歷史K線：twstock.Stock(stock_id) 逐月抓，直連證交所/櫃買，免 token
- 即時報價：twstock.realtime.get_raw() 批次查，含昨收/開高低/累積成交量
- 代碼對照：twstock.codes → {code: name/group(產業)/market}
- 容錯：twstock 或交易所掛掉 → 回 None / 空 DataFrame，不影響主流程
- 節制：每檔每月份抓取間隔 TWSTOCK_MIN_INTERVAL 秒（證交所會封鎖狂打 IP）
"""
from __future__ import annotations

import time
from datetime import date
from typing import Optional

import pandas as pd

TWSTOCK_MIN_INTERVAL = 0.3

# 每個 (stock_id, source) 上次抓取時間
_last_fetch: dict[tuple[str, str], float] = {}


def _throttle(stock_id: str, source: str = "price") -> None:
    key = (stock_id, source)
    now = time.time()
    wait = TWSTOCK_MIN_INTERVAL - (now - _last_fetch.get(key, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last_fetch[key] = time.time()


def _import_twstock():
    import twstock

    return twstock


def get_twstock_price_history(
    stock_id: str, start: str, as_of: str | None = None
) -> pd.DataFrame:
    """twstock 歷史K線（FinMind 備援）。

    回欄位與 FinMind TaiwanStockPrice 正規化後相同：
        date, open, high, low, close, volume
    依 (year, month) 逐月抓並節流；任一個月失敗就跳過，全部失敗回空 DataFrame。
    """
    try:
        tw = _import_twstock()
    except Exception:
        return pd.DataFrame()
    try:
        start_dt = pd.to_datetime(start).date()
    except Exception:
        return pd.DataFrame()
    if start_dt > date.today():
        return pd.DataFrame()

    rows = []
    s = tw.Stock(stock_id)
    y, m = start_dt.year, start_dt.month
    today = date.today()
    while (y, m) <= (today.year, today.month):
        _throttle(stock_id)
        try:
            data = s.fetch(y, m)
        except Exception:
            data = []
        rows.extend(data or [])
        m += 1
        if m > 12:
            m = 1
            y += 1

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": float(r.open or 0.0),
                "high": float(r.high or 0.0),
                "low": float(r.low or 0.0),
                "close": float(r.close or 0.0),
                "volume": int(r.capacity or 0),
            }
            for r in rows
        ]
    )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    df = df[df["date"] >= pd.to_datetime(start)]
    if as_of:
        df = df[df["date"] <= pd.to_datetime(as_of)]
    return df.reset_index(drop=True)


def get_realtime_quotes(stock_ids: list[str]) -> dict[str, dict]:
    """twstock 即時報價（批次）。

    回 {stock_id: {stock_id, name, date, time, open, high, low, price,
    prev_close, change, volume}}。整批抓不到 / 個別無資料就跳過。
    """
    if not stock_ids:
        return {}
    try:
        tw = _import_twstock()
        _throttle(",".join(stock_ids), "realtime")
        raw = tw.realtime.get_raw(stock_ids)
    except Exception:
        return {}

    out: dict[str, dict] = {}
    for m in raw.get("msgArray", []) or []:
        code = str(m.get("c", "")).strip()
        if not code:
            continue
        try:
            price = float(m.get("z") or 0.0)
            prev_close = float(m.get("y") or 0.0)
        except (TypeError, ValueError):
            continue
        out[code] = {
            "stock_id": code,
            "name": str(m.get("n", "") or ""),
            "date": str(m.get("d", "") or ""),
            "time": str(m.get("t", "") or ""),
            "open": _f(m.get("o")),
            "high": _f(m.get("h")),
            "low": _f(m.get("l")),
            "price": price,
            "prev_close": prev_close,
            "change": round(price - prev_close, 2),
            "volume": int(float(m.get("v") or 0.0)),
        }
    return out


def _f(v) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def get_stock_name(stock_id: str) -> Optional[str]:
    """twstock.codes 代碼→名稱備援（FinMind TaiwanStockInfo 掛掉時用）。"""
    try:
        tw = _import_twstock()
        info = tw.codes.get(str(stock_id))
        return info.name if info and info.name else None
    except Exception:
        return None


def get_stock_info_from_codes() -> pd.DataFrame:
    """把 twstock.codes 建成與 FinMind get_stock_info 相同 schema 的 DataFrame。

    回 stock_id, stock_name, industry_category, market_type。
    只留上市/上櫃一般股票（過濾權證、債券、指數等）。
    """
    try:
        tw = _import_twstock()
    except Exception:
        return pd.DataFrame()
    rows = []
    for code, info in tw.codes.items():
        if info.market not in ("上市", "上櫃"):
            continue
        rows.append(
            {
                "stock_id": str(info.code),
                "stock_name": info.name or "",
                "industry_category": info.group or "",
                "market_type": "上市" if info.market == "上市" else "上櫃",
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["stock_id"]).reset_index(drop=True)
