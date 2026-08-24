from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .config import CONFIG
from .data import get_fundamental, get_price_history
from .indicators import add_indicators, tech_score_at
from .backtest import backtest
from .volume import detect_patterns, verdict as volume_verdict
from .chips import chip_snapshot
from .loader import merge_params


def _to_native(v):
    """遞迴把 numpy 純量轉成原生 Python 型別（JSON 可序列化）"""
    if isinstance(v, dict):
        return {k: _to_native(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_native(x) for x in v]
    if isinstance(v, tuple):
        return tuple(_to_native(x) for x in v)
    if isinstance(v, np.generic):
        return v.item()
    return v


def _liquidity_avg_turnover(px: pd.DataFrame, days: int = 20) -> Optional[float]:
    """近 N 日平均成交金額（元）；無資料回 None。"""
    if "turnover" not in px.columns or len(px) == 0:
        return None
    tail = px.tail(days)
    avg = pd.to_numeric(tail["turnover"], errors="coerce").mean()
    return float(avg) if pd.notna(avg) else None


def _benchmark_0050(px: pd.DataFrame, years: int) -> Optional[float]:
    """同期買進持有 0050 的報酬（與個股資料同區間）。"""
    try:
        bench = get_price_history("0050", years)
        if bench.empty or len(bench) < 2:
            return None
        start_d = pd.to_datetime(px["date"].iloc[0])
        end_d = pd.to_datetime(px["date"].iloc[-1])
        b = bench[
            (pd.to_datetime(bench["date"]) >= start_d)
            & (pd.to_datetime(bench["date"]) <= end_d)
        ]
        if len(b) < 2:
            return None
        first = float(b["close"].iloc[0])
        last = float(b["close"].iloc[-1])
        return last / first - 1 if first > 0 else None
    except Exception:
        return None


def _suggested_lots(entry_price: float, position_pct: float, capital: float) -> int:
    """依本金與建議部位 % 換算整股張數（1 張 = 1000 股）。"""
    if entry_price <= 0:
        return 0
    budget = capital * position_pct / 100.0
    return int(budget // (entry_price * 1000))


def evaluate(stock_id: str, name: str, strategy: dict | None = None) -> Optional[dict]:
    """評估一檔股票。strategy 為策略 dict（含 params），不給就用預設值。"""
    params = merge_params(strategy)

    result = {
        "stock_id": stock_id,
        "name": name,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "strategy_id": (strategy or {}).get("id", "default"),
        "risk_notes": [],
    }

    try:
        fund = get_fundamental(stock_id)
        eps_vals = list(fund["eps"].values())
        roe_vals = list(fund["roe"].values())
        fund_pass = (
            len(eps_vals) >= 2
            and len(roe_vals) >= 2
            and min(eps_vals) > params["eps_threshold"]
            and min(roe_vals) > params["roe_threshold"]
        )

        px = get_price_history(stock_id, params["backtest_years"], adjusted=True)
        if len(px) < 100:
            result["action"] = "SKIP"
            result["risk_notes"].append("價格資料不足")
            return _to_native(result)

        avg_turnover = _liquidity_avg_turnover(px)
        if avg_turnover is not None and avg_turnover < params["min_avg_turnover"]:
            result["action"] = "SKIP"
            result["risk_notes"].append(
                f"流動性不足：20日均成交金額 {avg_turnover/10_000:.0f} 萬，"
                f"低於門檻 {params['min_avg_turnover']/10_000:.0f} 萬"
            )
            return _to_native(result)

        px = add_indicators(px)
        latest = px.iloc[-1]
        ts = tech_score_at(latest, params)
        bt = backtest(px, params)

        if params["use_volume_patterns"]:
            vp = detect_patterns(px)
        else:
            vp = {"patterns": [], "bonus": 0, "details": {}}

        fund_score = 100 if fund_pass else 40
        tech_score = max(0, min(100, ts["score"] + vp["bonus"]))
        winrate = bt.get("winrate") or 0.5
        bt_score = winrate * 100
        bench_0050 = _benchmark_0050(px, params["backtest_years"])

        chip_component = None
        if params.get("use_chips"):
            chips_date = pd.Timestamp(px["date"].iloc[-1]).strftime("%Y-%m-%d")
            chip_component = chip_snapshot(stock_id, as_of=chips_date)

        wf = params["weight_fundamental"]
        wt = params["weight_technical"]
        wb = params["weight_backtest"]
        wc = params.get("weight_chips", 0.0)

        # 加權平均（含籌碼面；籌碼資料缺時排除，不拖累原分數）
        weighted = [(fund_score, wf), (tech_score, wt), (bt_score, wb)]
        if chip_component and chip_component.get("score") is not None:
            weighted.append((chip_component["score"], wc))
        wsum = sum(w for _, w in weighted)
        if wsum > 0:
            signal_score = round(sum(s * w for s, w in weighted) / wsum, 1)
        else:
            signal_score = 0.0

        fund_gate = (not params["fundamental_pass_required"]) or fund_pass
        if (
            signal_score >= params["min_total_score_for_buy"]
            and fund_gate
            and tech_score >= params["min_tech_score_for_buy"]
        ):
            action = "BUY"
        elif signal_score >= 50:
            action = "WATCH"
        else:
            action = "SKIP"

        entry = float(latest["close"])
        stop_price = round(entry * (1 - params["stop_loss"]), 2)
        target_price = round(entry * (1 + params["target_return"]), 2)
        rr = round(params["target_return"] / params["stop_loss"], 2)
        position_pct = min(2.0 / (params["stop_loss"] * 100) * 100, 20.0)
        lots = _suggested_lots(entry, position_pct, params.get("capital", CONFIG["capital"]))
        entry_rule = (
            f"明日以開盤價進場，停損 -{params['stop_loss']*100:.0f}% / "
            f"停利 +{params['target_return']*100:.0f}%（下方參考價為今日收盤）"
        )
        if lots == 0:
            result["risk_notes"].append(
                f"以本金 {params.get('capital', CONFIG['capital']):,.0f} 元買不足 1 張，僅能零股"
            )

        if bt.get("samples", 0) < 8:
            result["risk_notes"].append(f"回測樣本僅 {bt.get('samples', 0)} 次，統計弱")
        bt_total = bt.get("total_return")
        if bt_total is not None and bt_total < 0:
            result["risk_notes"].append(
                f"近3年策略淨報酬 {bt_total*100:+.1f}%（已扣成本）為負"
            )
        if (
            bt_total is not None
            and bench_0050 is not None
            and bt_total < bench_0050
        ):
            result["risk_notes"].append(
                f"淨報酬落後同期0050（{bt_total*100:+.1f}% vs {bench_0050*100:+.1f}%）"
            )
        if bt.get("skipped_limit_up"):
            result["risk_notes"].append(
                f"回測 {bt['skipped_limit_up']} 筆訊號因開盤漲停無法成交已剔除"
            )
        if not fund_pass:
            result["risk_notes"].append("基本面未過門檻")
        if winrate < 0.5:
            result["risk_notes"].append(f"歷史勝率 {winrate*100:.0f}% 低於五成")
        if pd.notna(latest.get("bb_upper")) and latest["close"] > latest["bb_upper"]:
            result["risk_notes"].append("已突破布林上軌，追高風險")
        if "放量滯漲" in vp["patterns"]:
            result["risk_notes"].append("偵測到放量滯漲，高檔爆量疑似出貨")
        if chip_component:
            if chip_component.get("score") is None:
                result["risk_notes"].append("籌碼資料暫時缺")
            else:
                if (chip_component.get("total_net") or 0) < 0:
                    result["risk_notes"].append("三大法人賣超")
                mprev = chip_component.get("margin_prev") or 0
                mchg = chip_component.get("margin_chg") or 0
                if mprev > 0 and mchg / mprev > 0.05:
                    result["risk_notes"].append("融資單日暴增，過熱風險")

        chg_5d = (latest["close"] / px.iloc[-6]["close"] - 1) * 100 if len(px) >= 6 else 0
        chg_20d = (latest["close"] / px.iloc[-21]["close"] - 1) * 100 if len(px) >= 21 else 0
        vol_5 = px["volume"].iloc[-5:].mean()
        vol_20 = px["volume"].iloc[-20:].mean()
        vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1
        high_252 = px["high"].iloc[-252:].max() if len(px) >= 252 else px["high"].max()
        low_252 = px["low"].iloc[-252:].min() if len(px) >= 252 else px["low"].min()
        pct_from_high = (latest["close"] / high_252 - 1) * 100
        above_ma20 = latest["close"] > latest["ma20"] if pd.notna(latest["ma20"]) else False
        above_ma60 = latest["close"] > latest["ma60"] if pd.notna(latest["ma60"]) else False

        result.update({
            "action": action,
            "signal_score": signal_score,
            "components": {
                "fundamental_pass": fund_pass,
                "eps_min": min(eps_vals) if eps_vals else None,
                "roe_min": min(roe_vals) if roe_vals else None,
                "tech_score": tech_score,
                "tech_signals": ts["signals"],
                "backtest_winrate": winrate,
                "backtest_samples": bt.get("samples", 0),
                "backtest_total_return": bt.get("total_return"),
                "backtest_max_drawdown": bt.get("max_drawdown"),
                "backtest_profit_factor": bt.get("profit_factor"),
                "backtest_sharpe": bt.get("sharpe"),
                "benchmark_0050_return": round(bench_0050, 4) if bench_0050 is not None else None,
                "avg_turnover_20d": (
                    round(avg_turnover, 0) if avg_turnover is not None else None
                ),
                "suggested_lots": lots,
                "volume_patterns": vp["patterns"],
                "volume_details": vp["details"],
                "volume_bonus": vp["bonus"],
                "volume_verdict": volume_verdict(vp["patterns"]),
                "chips": chip_component or {"score": None, "note": "use_chips 未啟用"},
            },
            "trend": {
                "chg_5d": round(chg_5d, 2),
                "chg_20d": round(chg_20d, 2),
                "vol_ratio": round(vol_ratio, 2),
                "pct_from_high": round(pct_from_high, 1),
                "above_ma20": bool(above_ma20),
                "above_ma60": bool(above_ma60),
            },
            "entry_price": entry,
            "stop_loss_price": stop_price,
            "target_price": target_price,
            "risk_reward_ratio": rr,
            "position_size_pct": round(position_pct, 1),
            "suggested_lots": lots,
            "entry_rule": entry_rule,
        })
        return _to_native(result)

    except Exception as e:
        result["action"] = "ERROR"
        result["risk_notes"].append(f"錯誤: {str(e)[:80]}")
        return _to_native(result)
