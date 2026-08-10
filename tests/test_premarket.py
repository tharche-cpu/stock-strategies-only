"""premarket 快報格式化測試：含即時報價區塊。"""
from stock_strategies.notify import format_premarket


def test_format_premarket_with_quotes():
    night = {
        "date": "2026-08-10", "pct": 0.8, "label": "小漲", "emoji": "🟢",
        "bias": "bull", "spread": 150.0, "close": 22300.0, "volume": 120000,
        "direction": "今日開盤偏多",
    }
    signals = [
        {"date": "2026-08-10", "stock_id": "2330", "name": "台積電",
         "action": "BUY", "signal_score": 87.7},
        {"date": "2026-08-10", "stock_id": "2603", "name": "長榮",
         "action": "WATCH", "signal_score": 54.4},
    ]
    quotes = {
        "2330": {"stock_id": "2330", "name": "台積電", "date": "20260810",
                 "time": "14:30:00", "open": 2390.0, "high": 2410.0, "low": 2380.0,
                 "price": 2380.0, "prev_close": 2370.0, "change": 10.0, "volume": 18833},
        "2603": {"stock_id": "2603", "name": "長榮", "date": "20260810",
                 "time": "14:30:00", "open": 214.5, "high": 215.5, "low": 213.5,
                 "price": 214.0, "prev_close": 213.5, "change": 0.5, "volume": 14048},
    }
    msg = format_premarket(night, signals, quotes)
    assert "盤前即時報價" in msg
    assert "2330" in msg and "台積電" in msg
    assert "2380.00" in msg          # 現價
    assert "+10.00" in msg or "+10" in msg  # 漲跌點
    assert "18,833" in msg            # 累積量（千分位）


def test_format_premarket_no_quotes_still_works():
    night = {"date": "2026-08-10", "pct": 0.5, "label": "平盤", "emoji": "⚪",
             "bias": "flat", "spread": 0.0, "close": 22000.0, "volume": 0,
             "direction": "方向中性"}
    signals = [
        {"date": "2026-08-10", "stock_id": "2317", "name": "鴻海",
         "action": "BUY", "signal_score": 80.0},
    ]
    msg = format_premarket(night, signals)
    assert "盤前即時報價" not in msg
    assert "2317" in msg
