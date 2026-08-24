"""除權息還原、流動性門檻、張數換算的單元測試（mock，不打 FinMind）。"""
import numpy as np
import pandas as pd
import pytest

from stock_strategies import data
from stock_strategies.evaluate import _liquidity_avg_turnover, _suggested_lots


# ── 除權息還原 ──


def test_dividend_adjust_scales_history_keeps_latest(monkeypatch):
    # 30 天價格 100 → 除息日(第20天)前一日收盤 100、每股現金股利 5 → 因子 0.95
    n = 30
    dates = pd.date_range("2026-06-01", periods=n, freq="B")
    raw = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000] * n,
        }
    )
    ex_date = dates[19]
    div = pd.DataFrame(
        [{"date": str(ex_date.date()), "stock_id": "2330",
          "before_price": 100.0, "stock_and_cache_dividend": 5.0}]
    )

    def fake_cached(dataset, stock_id, start, **kw):
        return div if dataset == "TaiwanStockDividendResult" else pd.DataFrame()

    monkeypatch.setattr(data, "fetch_finmind_cached", fake_cached)

    adj = data._dividend_adjust(raw.copy(), "2330")
    # 最新一天不變
    assert adj["close"].iloc[-1] == pytest.approx(100.0)
    # 除息日當天起不變
    assert adj["close"].iloc[19] == pytest.approx(100.0)
    # 除息日之前的歷史 × 0.95
    assert adj["close"].iloc[0] == pytest.approx(95.0)
    assert adj["open"].iloc[5] == pytest.approx(95.0)
    assert adj["high"].iloc[10] == pytest.approx(101.0 * 0.95)
    # volume 不受影響
    assert adj["volume"].iloc[0] == 1000


def test_dividend_adjust_no_events_returns_same(monkeypatch):
    monkeypatch.setattr(
        data, "fetch_finmind_cached", lambda *a, **k: pd.DataFrame()
    )
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5),
            "open": [10.0] * 5, "high": [11.0] * 5,
            "low": [9.0] * 5, "close": [10.0] * 5, "volume": [1] * 5,
        }
    )
    out = data._dividend_adjust(df.copy(), "2330")
    assert out["close"].tolist() == df["close"].tolist()


def test_get_price_history_adjusted_flag(monkeypatch):
    """adjusted=True 時應呼叫 _dividend_adjust；False 不會。"""
    n = 120
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n),
            "max": [50.0] * n, "min": [48.0] * n,
            "close": [49.0] * n, "open": [49.0] * n,
            "Trading_Volume": [500] * n,
            "Trading_money": [24_500_000.0] * n,
        }
    )
    calls = {"adjust": 0}

    def fake_adjust(df, sid):
        calls["adjust"] += 1
        return df

    monkeypatch.setattr(data, "fetch_finmind_cached",
                        lambda ds, sid, st, **k: raw.copy())
    monkeypatch.setattr(data, "_dividend_adjust", fake_adjust)

    data.get_price_history("2330", years=1)  # 預設不還原
    assert calls["adjust"] == 0
    out = data.get_price_history("2330", years=1, adjusted=True)
    assert calls["adjust"] == 1
    assert "turnover" in out.columns and out["turnover"].iloc[0] == 24_500_000.0
    assert "high" in out.columns and "volume" in out.columns


# ── 流動性門檻 ──


def test_liquidity_avg_turnover():
    px = pd.DataFrame({"turnover": [10_000_000.0] * 10 + [20_000_000.0] * 20})
    avg = _liquidity_avg_turnover(px)
    assert avg == pytest.approx(20_000_000.0)


def test_liquidity_none_without_column():
    assert _liquidity_avg_turnover(pd.DataFrame({"close": [1, 2]})) is None
    assert _liquidity_avg_turnover(pd.DataFrame()) is None


def test_liquidity_low_turnover_nan():
    px = pd.DataFrame({"turnover": [np.nan] * 20})
    assert _liquidity_avg_turnover(px) is None


# ── 張數換算 ──


def test_suggested_lots_rounds_down_to_board_lot():
    # 本金 300k、部位 20% = 60k 預算
    assert _suggested_lots(30.0, 20.0, 300_000) == 2      # 60k // 30k = 2 張
    assert _suggested_lots(100.0, 20.0, 300_000) == 0     # 60k < 100k = 0 張
    assert _suggested_lots(2330.0, 20.0, 300_000) == 0    # 高價股零股
    assert _suggested_lots(50.0, 100.0, 300_000) == 6     # 300k // 50k
    assert _suggested_lots(0, 20.0, 300_000) == 0
