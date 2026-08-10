"""twstock 資料層測試：mock twstock，不打交易所。"""
from datetime import datetime

import pandas as pd
import pytest

import stock_strategies.twstock_source as tws


class _Data:
    """模擬 twstock.Data（namedtuple 樣態）。"""

    def __init__(self, date, open, high, low, close, capacity, change=0.0,
                 turnover=0.0, transaction=0, note=""):
        self.date = date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.capacity = capacity
        self.change = change
        self.turnover = turnover
        self.transaction = transaction
        self.note = note


class _FakeStock:
    def __init__(self, sid, days):
        self.sid = sid
        self.days = days  # list of (date_str, o, h, l, c, vol)

    def fetch(self, year, month):
        out = []
        for d, o, h, l, c, v in self.days:
            dt = datetime(year, month, 1)
            if datetime.strptime(d, "%Y-%m-%d").month == month:
                out.append(_Data(datetime.strptime(d, "%Y-%m-%d"), o, h, l, c, v))
        return out


class _FakeCodes:
    """模擬 twstock.codes 的 dict of StockCodeInfo。"""

    class Info:
        def __init__(self, code, name, market, group):
            self.code = code
            self.name = name
            self.market = market
            self.group = group

    def __init__(self, mapping):
        self._m = mapping

    def get(self, key):
        v = self._m.get(str(key))
        if v:
            return self.Info(str(v[0]), v[1], v[2], v[3])
        return None

    def items(self):
        return [(k, self.get(k)) for k in self._m]


def _fake_twstock(module, stock_days=None, codes_map=None, realtime_raw=None):
    """把 twstock 掛到 tws 的 import 層。回傳 fake module。"""

    class FakeTwstock:
        def __init__(self):
            self.codes = _FakeCodes(codes_map or {})
            self.realtime = type("rt", (), {"get_raw": lambda *a, **k: realtime_raw or {}})()

        def Stock(self, sid):
            days = (stock_days or {}).get(str(sid), [])
            return _FakeStock(sid, days)

    fake = FakeTwstock()
    monkeypatch = module  # placeholder
    return fake


@pytest.fixture
def fake_twstock(monkeypatch):
    def install(stock_days=None, codes_map=None, realtime_raw=None):
        fake = _fake_twstock(None, stock_days, codes_map, realtime_raw)
        monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
        return fake

    return install


def test_price_history_normalized(monkeypatch):
    days = [
        ("2026-08-03", 2390, 2395, 2365, 2370, 35209944),
        ("2026-08-04", 2335, 2360, 2310, 2320, 41021199),
        ("2026-08-05", 2385, 2415, 2370, 2405, 36782301),
    ]
    fake = _fake_twstock(None, {"2330": days})
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    df = tws.get_twstock_price_history("2330", "2026-08-01")
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert df.iloc[-1]["close"] == 2405
    assert df.iloc[-1]["volume"] == 36782301
    assert str(df.iloc[-1]["date"].date()) == "2026-08-05"


def test_price_history_as_of_slice(monkeypatch):
    days = [
        ("2026-08-03", 2390, 2395, 2365, 2370, 35209944),
        ("2026-08-04", 2335, 2360, 2310, 2320, 41021199),
    ]
    fake = _fake_twstock(None, {"2330": days})
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    df = tws.get_twstock_price_history("2330", "2026-08-01", as_of="2026-08-03")
    assert len(df) == 1
    assert str(df.iloc[0]["date"].date()) == "2026-08-03"


def test_price_history_import_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(tws, "_import_twstock", lambda: (_ for _ in ()).throw(ImportError()))
    assert tws.get_twstock_price_history("2330", "2026-01-01").empty


def test_price_history_bad_start_returns_empty(monkeypatch):
    fake = _fake_twstock(None, {})
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    assert tws.get_twstock_price_history("2330", "not-a-date").empty


def test_realtime_quotes_batch(monkeypatch):
    raw = {
        "msgArray": [
            {
                "c": "2330", "n": "台積電", "d": "20260810", "t": "14:30:00",
                "z": "2380.0000", "y": "2370.0000",
                "o": "2390.0000", "h": "2410.0000", "l": "2380.0000",
                "v": "18833",
            },
            {
                "c": "2603", "n": "長榮", "d": "20260810", "t": "14:30:00",
                "z": "214.0000", "y": "213.5000",
                "o": "214.5000", "h": "215.5000", "l": "213.5000",
                "v": "14048",
            },
        ]
    }
    fake = _fake_twstock(None, {}, realtime_raw=raw)
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    out = tws.get_realtime_quotes(["2330", "2603"])
    assert set(out) == {"2330", "2603"}
    q = out["2330"]
    assert q["price"] == 2380.0
    assert q["change"] == 10.0
    assert q["volume"] == 18833
    assert q["name"] == "台積電"


def test_realtime_quotes_empty_input():
    assert tws.get_realtime_quotes([]) == {}


def test_stock_name_from_codes(monkeypatch):
    fake = _fake_twstock(None, {}, codes_map={"2330": ("2330", "台積電", "上市", "半導體")})
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    assert tws.get_stock_name("2330") == "台積電"
    assert tws.get_stock_name("9999") is None


def test_stock_info_from_codes_filters_markets(monkeypatch):
    fake = _fake_twstock(
        None, {},
        codes_map={
            "2330": ("2330", "台積電", "上市", "半導體"),
            "00632R": ("00632R", "元大台灣50反1", "上市", "ETF"),
            "1234": ("1234", "某興櫃", "興櫃", "生技"),
        },
    )
    monkeypatch.setattr(tws, "_import_twstock", lambda: fake)
    df = tws.get_stock_info_from_codes()
    assert {"stock_id", "stock_name", "industry_category", "market_type"}.issubset(df.columns)
    assert "00632R" in set(df["stock_id"])  # 上市 ETF 保留
    assert "1234" not in set(df["stock_id"])  # 興櫃過濾
    row = df.set_index("stock_id").loc["2330"]
    assert row["stock_name"] == "台積電"
    assert row["industry_category"] == "半導體"
