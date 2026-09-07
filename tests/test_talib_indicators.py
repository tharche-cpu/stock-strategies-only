"""TA-Lib 補充指標（ADX/RSI/WR）的單元測試。"""
import numpy as np
import pandas as pd
import pytest

from stock_strategies import indicators as ind
from stock_strategies.indicators import add_indicators, tech_score_at


def _trend_df(n=80, base=100.0, step=0.5):
    """持續上漲趨勢 → ADX 高、RSI 高。"""
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = base + np.arange(n) * step
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": [1000000] * n,
        }
    )


def test_talib_columns_added():
    df = add_indicators(_trend_df())
    for col in ("adx", "rsi", "wr"):
        assert col in df.columns


def test_trend_series_has_meaningful_adx_rsi():
    df = add_indicators(_trend_df())
    last = df.iloc[-1]
    # 一路上漲 → ADX 強勢趨勢、RSI 偏多
    assert pd.notna(last["adx"])
    assert last["adx"] >= 15
    assert pd.notna(last["rsi"]) and last["rsi"] > 50


def test_adx_signal_adds_to_score_when_enabled():
    df = add_indicators(_trend_df())
    last = df.iloc[-1]
    row = last
    # 只開 ADX：分數應主要由 ADX 訊號給出
    params = {
        "use_ma_alignment": False,
        "use_bollinger_bounce": False,
        "use_kd_golden_cross": False,
        "use_macd_bullish": False,
        "use_adx_trend": True,
    }
    out = tech_score_at(row, params)
    assert out["score"] >= 40
    assert any("ADX" in s or "趨勢" in s for s in out["signals"])


def test_adx_signal_disabled_when_turned_off():
    df = add_indicators(_trend_df())
    row = df.iloc[-1]
    params = {
        "use_ma_alignment": False,
        "use_bollinger_bounce": False,
        "use_kd_golden_cross": False,
        "use_macd_bullish": False,
        "use_adx_trend": False,
    }
    out = tech_score_at(row, params)
    assert out["score"] == 0


def test_adx_default_enabled_does_not_change_other_signal_value():
    """加 ADX 後其它訊號因分母變 5，單獨訊號權重應仍合理（0~100）。"""
    df = add_indicators(_trend_df())
    row = df.iloc[-1]
    out = tech_score_at(row, {})
    assert 0 <= out["score"] <= 100


def test_talib_unavailable_returns_nan_columns(monkeypatch):
    monkeypatch.setattr(ind, "_talib", lambda: None)
    df = add_indicators(_trend_df())
    assert pd.isna(df["adx"].iloc[-1])
    # 無 TA-Lib 時 ADX 訊號不會算分，也不崩潰
    row = df.iloc[-1]
    out = tech_score_at(row, {"use_adx_trend": True})
    assert "score" in out
