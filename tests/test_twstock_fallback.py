"""FinMind 掛掉時 twstock 備援的接線測試（mock，不打交易所）。"""
from datetime import datetime

import pandas as pd

from stock_strategies import data, context
from stock_strategies import twstock_source as tws


class _Data:
    def __init__(self, date, open, high, low, close, capacity):
        self.date = date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.capacity = capacity


class _FakeStock:
    def __init__(self, days):
        self.days = days

    def fetch(self, year, month):
        return [
            _Data(datetime.strptime(d, "%Y-%m-%d"), o, h, l, c, v)
            for d, o, h, l, c, v in self.days
        ]


def _install_fake_twstock(monkeypatch):
    days = [
        ("2026-08-03", 2390, 2395, 2365, 2370, 35209944),
        ("2026-08-04", 2335, 2360, 2310, 2320, 41021199),
        ("2026-08-05", 2385, 2415, 2370, 2405, 36782301),
    ]
    fake = type("T", (), {})()
    fake.codes = {}
    fake.realtime = type("rt", (), {})()
    fake.realtime.get_raw = lambda *a, **k: {}
    fake.Stock = lambda *a, **k: _FakeStock(days)
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)


def test_get_price_history_falls_back_when_finmind_empty(monkeypatch):
    monkeypatch.setattr(data, "fetch_finmind_cached", lambda *a, **k: pd.DataFrame())
    _install_fake_twstock(monkeypatch)
    df = data.get_price_history("2330", years=1)
    assert not df.empty
    assert {"date", "open", "high", "low", "close", "volume"}.issubset(df.columns)
    assert df.iloc[-1]["close"] == 2405


def test_get_price_history_keeps_finmind_when_available(monkeypatch):
    raw = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-03", "2026-08-04"]),
        "open": [10, 11], "max": [10.5, 11.5], "min": [9.5, 10.5],
        "close": [10.2, 11.2], "Trading_Volume": [1000, 1100],
    })
    monkeypatch.setattr(data, "fetch_finmind_cached", lambda *a, **k: raw.copy())
    monkeypatch.setattr(data, "get_twstock_price_history",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該進備援")))
    df = data.get_price_history("2330", years=1)
    assert df.iloc[-1]["volume"] == 1100


def test_context_price_history_fallback(monkeypatch):
    monkeypatch.setattr(context, "fetch_finmind_cached", lambda *a, **k: pd.DataFrame())
    _install_fake_twstock(monkeypatch)
    df = context.get_price_history_cached("2330", "2026-08-01")
    assert not df.empty
    assert str(df.iloc[-1]["date"].date()) == "2026-08-05"
