"""全市場 BUY 掃描（scan.py + scan_buy_row）的單元測試。"""
import pandas as pd

from stock_strategies import scan
from stock_strategies.sheet import SCAN_HEADERS, scan_buy_row


def _fake_info():
    return pd.DataFrame(
        [
            {"stock_id": "2330", "stock_name": "台積電", "market_type": "twse"},
            {"stock_id": "3687", "stock_name": "歐買尬", "market_type": "tpex"},
            {"stock_id": "0050", "stock_name": "元大台灣50ETF", "market_type": "twse"},
            {"stock_id": "00632R", "stock_name": "元大台灣50反1ETF", "market_type": "twse"},
            {"stock_id": "12345", "stock_name": "某興櫃股", "market_type": "emerging"},
            {"stock_id": "ABCD", "stock_name": "非數字代碼", "market_type": "twse"},
            {"stock_id": "2888", "stock_name": "新光金", "market_type": "twse"},
        ]
    )


def test_common_stock_universe_filters_etf_and_boards(monkeypatch):
    monkeypatch.setattr(scan, "get_stock_info", lambda: _fake_info())
    out = scan.common_stock_universe()
    assert set(out["stock_id"]) == {"2330", "3687", "2888"}
    assert "0050" not in set(out["stock_id"])      # ETF
    assert "12345" not in set(out["stock_id"])     # 興櫃
    assert "ABCD" not in set(out["stock_id"])      # 非數字代碼


def test_top_pool_ranks_by_turnover():
    prog = pd.DataFrame(
        [
            {"stock_id": "2330", "avg_turnover_20d": 30_000_000_000},
            {"stock_id": "2888", "avg_turnover_20d": 2_000_000_000},
            {"stock_id": "3687", "avg_turnover_20d": None},
        ]
    )
    assert scan.top_pool(prog, n=2) == ["2330", "2888"]


def test_top_pool_n_caps_size():
    prog = pd.DataFrame(
        [{"stock_id": str(i), "avg_turnover_20d": i} for i in range(1, 6)]
    )
    assert len(scan.top_pool(prog, n=3)) == 3


def test_stock_turnover_missing_turnover_column(monkeypatch):
    monkeypatch.setattr(
        scan, "fetch_finmind_cached", lambda *a, **k: pd.DataFrame({"date": ["2026-01-01"]})
    )
    assert scan._stock_turnover("2330") is None


def _fake_buy_record():
    return {
        "date": "2026-09-09",
        "stock_id": "2330",
        "name": "台積電",
        "signal_score": 82.5,
        "entry_price": 900.0,
        "stop_loss_price": 828.0,
        "target_price": 990.0,
        "risk_reward_ratio": 1.25,
        "position_size_pct": 25.0,
        "suggested_lots": 1,
        "risk_notes": ["ADX 29 進入強勢趨勢"],
        "components": {
            "tech_score": 60,
            "backtest_winrate": 0.7,
            "backtest_samples": 25,
            "backtest_total_return": 0.87,
            "benchmark_0050_return": 0.32,
            "avg_turnover_20d": 12_345_678,
            "adx": 29.0,
            "adx_verdict": "趨勢",
            "rsi": 61.0,
            "volume_verdict": "放量上攻",
            "tech_signals": ["均線多頭", "ADX強勢趨勢"],
        },
    }


def test_scan_buy_row_aligns_with_headers():
    row = scan_buy_row(_fake_buy_record(), strategy_id="default")
    assert len(row) == len(SCAN_HEADERS)
    assert row[2] == "2330"
    assert row[16] == round(12_345_678 / 10_000)   # avg_turnover_wan
    assert row[18] == "趨勢"                        # adx_verdict
    assert "ADX" in row[22]                        # risk_notes


def test_scan_buy_row_tolerates_empty_components():
    row = scan_buy_row({"stock_id": "9999", "action": "BUY"})
    assert len(row) == len(SCAN_HEADERS)
    assert row[2] == "9999"