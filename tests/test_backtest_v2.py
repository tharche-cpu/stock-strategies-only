"""backtest v2：交易成本、樣本不重疊、漲停不可成交、績效統計。"""
import numpy as np
import pandas as pd
import pytest

from stock_strategies import backtest as bt_mod
from stock_strategies.backtest import backtest, round_trip_cost


def _df(n=90, base=100.0):
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [base] * n,
            "high": [base + 1] * n,
            "low": [base - 1] * n,
            "close": [base] * n,
            "volume": [1000000] * n,
        }
    )


@pytest.fixture(autouse=True)
def _all_signals(monkeypatch):
    monkeypatch.setattr(bt_mod, "tech_score_at", lambda row, params=None: {"score": 100, "signals": []})


def _hit_target_after_entry(df, idx_signal=60, gain=0.10):
    """讓訊號日 idx 的下一筆進場後，future 高點觸及停利。"""
    entry_idx = idx_signal + 1
    entry = df.loc[entry_idx, "open"]
    df.loc[entry_idx + 2 :, "high"] = entry * (1 + gain)
    df.loc[entry_idx + 2 :, "low"] = entry * 0.99  # 不觸停損
    return df


def test_cost_applied_to_returns():
    df = _df()
    df = _hit_target_after_entry(df, gain=0.10)
    bt = backtest(df)
    cost = round_trip_cost()
    assert bt["samples"] == 1
    assert bt["winrate"] == 1.0
    assert bt["avg_return"] == pytest.approx(round(0.10 - cost, 4))
    assert bt["avg_gross_return"] == pytest.approx(0.10)


def test_small_gain_counts_as_loss_after_cost():
    df = _df(base=50.0)
    # 毛報酬 +0.3% < 成本 0.585% → 淨值為負，應算賠
    df = _hit_target_after_entry(df, gain=-99)  # 先清掉 target 設定
    df.loc[:, "high"] = 51.0
    df.loc[:, "low"] = 49.0
    df.loc[80:, "close"] = 50.15  # 期末收盤微漲 0.3%
    bt = backtest(df)
    assert bt["samples"] >= 1
    assert bt["avg_return"] < 0
    assert bt["winrate"] < 1.0


def test_samples_do_not_overlap():
    n = 200
    df = _df(n=n)
    # 每天都訊號 → 舊版會取 n-81 筆高度重疊樣本；新版每筆間隔 ≥ hold+2
    bt = backtest(df)
    candidates = n - 60 - 21
    assert bt["samples"] >= 2
    assert bt["samples"] < candidates * 0.5


def test_limit_up_open_is_unfillable():
    df = _df()
    df = _hit_target_after_entry(df, gain=0.10)
    # 所有候選進場日開盤都鎖漲停（昨收 100 → 開盤 110）
    for i in range(61, 70):
        df.loc[i, "open"] = df.loc[i - 1, "close"] * 1.10
    bt = backtest(df)
    assert bt["skipped_limit_up"] >= 1
    assert bt["samples"] == 0


def test_stats_fields_present():
    df = _df(n=150)
    df = _hit_target_after_entry(df, gain=0.10)
    bt = backtest(df)
    for key in (
        "total_return", "max_drawdown", "profit_factor", "sharpe",
        "benchmark_return", "excess_return", "cost_round_trip",
    ):
        assert key in bt
    assert bt["total_return"] is not None and bt["total_return"] > 0
    assert bt["max_drawdown"] is None or bt["max_drawdown"] <= 0
    assert isinstance(bt["benchmark_return"], float)


def test_no_signals_returns_empty_with_cost():
    df = _df(n=80)
    monkey_none = {"min_tech_score_for_signal": 101}
    bt = backtest(df, params=monkey_none)
    assert bt["samples"] == 0
    assert bt["cost_round_trip"] == round_trip_cost(monkey_none)


def test_round_trip_cost_value():
    # 0.1425% × 2 + 0.3% = 0.585%
    assert round_trip_cost(None) == pytest.approx(0.00585)
