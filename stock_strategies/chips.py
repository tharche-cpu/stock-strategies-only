"""twchips 籌碼資料層：證交所三大法人個股買賣超 + 融資融券。

- 資料源：twchips（直接抓 TWSE 官網，免註冊 / 免 token）
- 快取：.cache/chips/<stock_id>.json，同一交易日不重複抓交易所
- 容錯：交易所改版 / 被鎖 IP / 套件壞掉 → 一律回 None，不影響選股主流程
- 節制：每檔每資料源抓取間隔 TWSE_MIN_INTERVAL 秒（證交所會封鎖狂打 IP）
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

CHIPS_CACHE_DIR = os.environ.get(
    "CHIPS_CACHE_DIR",
    str(Path(__file__).resolve().parent.parent / ".cache" / "chips"),
)

TWSE_MIN_INTERVAL = 0.5
_MAX_WALKBACK = 6  # 資料還沒公布時，往回最多找幾個交易日

# twchips 回傳欄位（交易所原文） → 本模組欄位
_INST_COLS = {
    "外陸資買賣超股數(不含外資自營商)": "foreign_net",
    "外資自營商買賣超股數": "foreign_dealer_net",
    "投信買賣超股數": "trust_net",
    "自營商買賣超股數": "dealer_net",
    "三大法人買賣超股數": "total_net",
}
_MARGIN_COLS = {
    "融資前日餘額": "margin_prev",
    "融資今日餘額": "margin_balance",
    "融券前日餘額": "short_prev",
    "融券今日餘額": "short_balance",
}

# 每個（stock_id, 資料源）上次抓取時間，避免連續請求打爆交易所
_last_fetch: dict[tuple[str, str], float] = {}
# 記憶體去重：同一 (stock, 資料源, as_of) 在一支程序內只抓一次
_tried_mem: dict[tuple[str, str, str], dict | None] = {}


def _cache_dir() -> Path:
    return Path(
        os.environ.get(
            "CHIPS_CACHE_DIR",
            str(Path(__file__).resolve().parent.parent / ".cache" / "chips"),
        )
    )


def _cache_path(stock_id: str) -> Path:
    return _cache_dir() / f"{stock_id}.json"


def _load_cache(stock_id: str) -> dict:
    try:
        with open(_cache_path(stock_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(stock_id: str, data: dict) -> None:
    try:
        p = _cache_path(stock_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _throttle(stock_id: str, source: str) -> None:
    key = (stock_id, source)
    now = time.time()
    last = _last_fetch.get(key, 0.0)
    wait = TWSE_MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_fetch[key] = time.time()


def _fetch_frame(stock_id: str, source: str, as_of: str):
    """抓單一資料源，walk-back 到有資料的日期。回 (date_str, dict | None)。"""
    from twchips import twse

    for offset in range(_MAX_WALKBACK):
        day = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=offset)).strftime(
            "%Y-%m-%d"
        )
        try:
            _throttle(stock_id, source)
            if source == "institutional":
                df = twse.institutional_stocks(day, stock=stock_id)
                col_map, out_key = _INST_COLS, "inst"
            else:
                df = twse.margin_stocks(day, stock=stock_id)
                col_map, out_key = _MARGIN_COLS, "margin"
        except Exception:
            return None, None

        if df is None or df.empty:
            continue
        row = df.iloc[0]
        data: dict = {"date": day}
        missing = False
        for src_col, out_col in col_map.items():
            if src_col in df.columns:
                v = row[src_col]
                try:
                    v = float(v) if v is not None and not _is_na(v) else 0.0
                except (TypeError, ValueError):
                    v = 0.0
                data[out_col] = v
            else:
                missing = True
        if missing:
            return day, None
        # 融資融券算變動
        if source == "margin":
            prev = data.get("margin_prev", 0.0)
            cur = data.get("margin_balance", 0.0)
            data["margin_chg"] = cur - prev
            sprev = data.get("short_prev", 0.0)
            scur = data.get("short_balance", 0.0)
            data["short_chg"] = scur - sprev
        return day, data
    return None, None


def _is_na(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    try:
        import numpy as np

        return bool(np.isnan(v))
    except Exception:
        return False


def get_institutional(stock_id: str, as_of: str | None = None) -> Optional[dict]:
    """三大法人個股買賣超。回 {date, foreign_net, trust_net, dealer_net, total_net, ...} 或 None。"""
    as_of = as_of or date.today().strftime("%Y-%m-%d")
    mem_key = (stock_id, "institutional", as_of)
    if mem_key in _tried_mem:
        return _tried_mem[mem_key]

    cache = _load_cache(stock_id)
    cached = cache.get("institutional")
    # 磁碟快取：已抓過且日期不比 as_of 舊 → 沿用
    if cached and cached.get("date") and cached["date"] >= as_of:
        _tried_mem[mem_key] = cached
        return cached

    day, data = _fetch_frame(stock_id, "institutional", as_of)
    if data is None:
        _tried_mem[mem_key] = None
        return None
    cache["institutional"] = data
    _save_cache(stock_id, cache)
    _tried_mem[mem_key] = data
    return data


def get_margin(stock_id: str, as_of: str | None = None) -> Optional[dict]:
    """個股融資融券。回 {date, margin_balance, margin_chg, short_balance, short_chg, ...} 或 None。"""
    as_of = as_of or date.today().strftime("%Y-%m-%d")
    mem_key = (stock_id, "margin", as_of)
    if mem_key in _tried_mem:
        return _tried_mem[mem_key]

    cache = _load_cache(stock_id)
    cached = cache.get("margin")
    if cached and cached.get("date") and cached["date"] >= as_of:
        _tried_mem[mem_key] = cached
        return cached

    day, data = _fetch_frame(stock_id, "margin", as_of)
    if data is None:
        _tried_mem[mem_key] = None
        return None
    cache["margin"] = data
    _save_cache(stock_id, cache)
    _tried_mem[mem_key] = data
    return data


def chip_score(inst: Optional[dict], margin: Optional[dict]) -> Optional[int]:
    """籌碼面 0-100 分。資料拿不到 → None（由呼叫端視為中性、排除加權）。

    規則（透明、可調）：
    - 基準 50
    - 三大法人淨買超 >0：+12；否則 -12
    - 外資淨買超 >0：+13；否則 -13
    - 投信淨買超 >0：+10；否則 -8
    - 自營淨買超 >0：+5；否則 -5
    - 融資退場（減幅 >2%）：+5（散戶下車偏多）
    - 融資暴增（增幅 >5%）：-8（過熱風險）
    - 融券急增（增幅 >10%）：-5
    """
    if inst is None:
        return None
    score = 50.0
    total = inst.get("total_net") or 0.0
    score += 12 if total > 0 else -12
    score += 13 if (inst.get("foreign_net") or 0.0) > 0 else -13
    score += 10 if (inst.get("trust_net") or 0.0) > 0 else -8
    score += 5 if (inst.get("dealer_net") or 0.0) > 0 else -5

    if margin:
        prev = margin.get("margin_prev") or 0.0
        if prev > 0:
            chg_pct = (margin.get("margin_chg") or 0.0) / prev
            if chg_pct < -0.02:
                score += 5
            elif chg_pct > 0.05:
                score -= 8
        sprev = margin.get("short_prev") or 0.0
        if sprev > 0 and (margin.get("short_chg") or 0.0) / sprev > 0.10:
            score -= 5

    return int(max(0, min(100, round(score))))


def chip_snapshot(stock_id: str, as_of: str | None = None) -> dict:
    """合併法人 + 融資融券的單檔籌碼快照（供 evaluate / 報告使用）。

    一律回 dict（含 score=None 表示資料缺），避免呼叫端炸 KeyError。
    """
    inst = get_institutional(stock_id, as_of)
    margin = get_margin(stock_id, as_of)
    out: dict = {
        "score": None,
        "date": None,
        "note": "",
    }
    if inst is None:
        out["note"] = "籌碼資料暫時無法取得"
        return out
    out["date"] = inst.get("date")
    for k in ("foreign_net", "foreign_dealer_net", "trust_net", "dealer_net", "total_net"):
        out[k] = inst.get(k, 0.0)
    if margin:
        for k in ("margin_balance", "margin_chg", "short_balance", "short_chg",
                  "margin_prev", "short_prev"):
            out[k] = margin.get(k, 0.0)
    else:
        out["note"] = "融資融券資料暫時無法取得"
    out["score"] = chip_score(inst, margin)
    return out
