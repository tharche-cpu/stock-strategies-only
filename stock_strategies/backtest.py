import numpy as np
import pandas as pd

from .config import CONFIG
from .indicators import tech_score_at

# 開盤價 ≥ 昨收 ×(1+此值) 視為漲停鎖死、實際買不到（0.0995 避開 tick 舍入誤差）
LIMIT_UP_RATIO = 0.0995


def round_trip_cost(params: dict | None = None) -> float:
    """台股來回交易成本 = 手續費 ×2 + 證交稅。"""
    p = params or {}
    return 2 * float(p.get("fee_rate", CONFIG["fee_rate"])) + float(
        p.get("tax_rate", CONFIG["tax_rate"])
    )


def backtest(df: pd.DataFrame, params: dict | None = None) -> dict:
    """對歷史技術分達門檻的日子做持有 N 日結算（淨報酬版）。

    - 訊號日第 i 天收盤產生，進場為第 i+1 天開盤。
    - 樣本不重疊：上一筆出場前不取新樣本，避免連續訊號刷高勝率。
    - 漲停不可成交：進場日開盤鎖漲停 → 跳過該筆。
    - 淨報酬：每筆扣除來回成本（手續費×2 + 證交稅），勝負以淨報酬正負判定。

    回傳欄位：
      winrate / samples / avg_return（淨，向後相容）
      avg_gross_return, total_return（複利）, max_drawdown,
      profit_factor, sharpe, benchmark_return, excess_return,
      cost_round_trip, skipped_limit_up
    """
    if params is None:
        params = {}
    hold_days = int(params.get("hold_days", CONFIG["hold_days"]))
    min_score = int(params.get("min_tech_score_for_signal", CONFIG["min_tech_score_for_signal"]))
    target = float(params.get("target_return", CONFIG["target_return"]))
    stop = float(params.get("stop_loss", CONFIG["stop_loss"]))
    cost = round_trip_cost(params)

    indices = []
    for i in range(60, len(df) - hold_days - 1):
        if tech_score_at(df.iloc[i], params)["score"] >= min_score:
            indices.append(i)

    empty = {
        "winrate": None, "samples": 0, "avg_return": None,
        "avg_gross_return": None, "total_return": None, "max_drawdown": None,
        "profit_factor": None, "sharpe": None,
        "benchmark_return": None, "excess_return": None,
        "cost_round_trip": cost, "skipped_limit_up": 0,
    }
    if not indices:
        return empty

    wins = losses = 0
    skipped_limit_up = 0
    returns: list[float] = []
    gross_returns: list[float] = []
    last_exit_idx = -1  # 上一筆已佔用的最後 K 棒位置

    for idx in indices:
        if idx <= last_exit_idx:
            continue  # 樣本重疊 → 跳過

        next_day = df.iloc[idx + 1]
        entry = next_day.get("open")
        if entry is None or pd.isna(entry) or entry <= 0:
            continue

        prev_close = df.iloc[idx]["close"]
        if pd.notna(prev_close) and prev_close > 0 and entry >= prev_close * (1 + LIMIT_UP_RATIO):
            skipped_limit_up += 1
            continue  # 開盤漲停買不到

        future = df.iloc[idx + 2 : idx + 2 + hold_days]
        if len(future) < hold_days:
            continue
        last_exit_idx = idx + 1 + hold_days

        hi, lo = future["high"].max(), future["low"].min()
        fc = future.iloc[-1]["close"]

        hit_target = hi >= entry * (1 + target)
        hit_stop = lo <= entry * (1 - stop)

        if hit_target and not hit_stop:
            gross_r = target
            wins += 1
        elif hit_stop:
            gross_r = -stop
            losses += 1
        else:
            gross_r = (fc - entry) / entry
            if gross_r - cost > 0:
                wins += 1
            else:
                losses += 1
        gross_returns.append(gross_r)
        returns.append(gross_r - cost)

    total = wins + losses
    if total == 0:
        return {**empty, "skipped_limit_up": skipped_limit_up}

    rets = np.array(returns)
    win_rets = rets[rets > 0]
    loss_rets = rets[rets <= 0]

    eq = np.cumprod(1.0 + rets)
    total_return = float(eq[-1] - 1.0)
    peak = np.maximum.accumulate(eq)
    max_dd = float(((eq - peak) / peak).min()) if len(eq) else None

    pf = (
        float(win_rets.sum() / abs(loss_rets.sum()))
        if len(loss_rets) and loss_rets.sum() != 0
        else (None if not len(win_rets) else float("inf"))
    )

    # 年化 Sharpe：以「每筆報酬」估計，年化交易次數 ≈ 樣本數 / 資料年跨度
    sharpe = None
    if len(rets) >= 2:
        std = float(rets.std(ddof=1))
        if std and std > 0 and len(df) >= 2:
            years_span = max((len(df) - 60) / 252.0, 1e-9)
            trades_per_year = len(rets) / years_span
            sharpe = float(rets.mean() / std * np.sqrt(trades_per_year))

    try:
        # benchmark = 同期買抱：與第一筆同一進場點買入、持有到資料末端
        first_entry = df["open"].iloc[indices[0] + 1]
        if pd.isna(first_entry) or first_entry <= 0:
            first_entry = df["close"].iloc[indices[0]]
        bench = float(df["close"].iloc[-1] / first_entry - 1) if first_entry > 0 else None
    except Exception:
        bench = None

    avg_net = float(np.mean(rets))
    return {
        "winrate": round(wins / total, 3),
        "samples": total,
        "avg_return": round(avg_net, 4),
        "avg_gross_return": round(float(np.mean(gross_returns)), 4),
        "total_return": round(total_return, 4),
        "max_drawdown": round(max_dd, 4) if max_dd is not None else None,
        "profit_factor": round(pf, 3) if pf is not None and pf != float("inf") else pf,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "benchmark_return": bench,
        "excess_return": round(avg_net - bench, 4) if bench is not None else None,
        "cost_round_trip": cost,
        "skipped_limit_up": skipped_limit_up,
    }
