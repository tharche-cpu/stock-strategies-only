"""籌碼面單元測試：mock twchips，不打交易所。"""
import pytest

import stock_strategies.chips as chips


def test_chip_score_all_buy():
    inst = {"total_net": 100, "foreign_net": 100, "trust_net": 50, "dealer_net": 20}
    margin = {"margin_prev": 1000, "margin_chg": -50, "short_prev": 100, "short_chg": 5}
    s = chips.chip_score(inst, margin)
    assert 60 < s <= 100


def test_chip_score_all_sell():
    inst = {"total_net": -100, "foreign_net": -100, "trust_net": -50, "dealer_net": -20}
    margin = {"margin_prev": 1000, "margin_chg": 100, "short_prev": 100, "short_chg": 20}
    s = chips.chip_score(inst, margin)
    assert 0 <= s < 40


def test_chip_score_no_inst_is_none():
    assert chips.chip_score(None, {}) is None


def test_chip_score_margin_spike_penalty():
    inst = {"total_net": 100, "foreign_net": 100, "trust_net": 50, "dealer_net": 20}
    calm = {"margin_prev": 1000, "margin_chg": 0, "short_prev": 100, "short_chg": 0}
    spike = {"margin_prev": 1000, "margin_chg": 200, "short_prev": 100, "short_chg": 0}
    assert chips.chip_score(inst, spike) < chips.chip_score(inst, calm)


def test_get_institutional_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIPS_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def fake_fetch(stock_id, source, as_of):
        calls["n"] += 1
        return "2026-08-07", {
            "date": "2026-08-07",
            "foreign_net": 1.0,
            "trust_net": 2.0,
            "dealer_net": 3.0,
            "total_net": 6.0,
            "foreign_dealer_net": 0.0,
        }

    monkeypatch.setattr(chips, "_fetch_frame", fake_fetch)
    a = chips.get_institutional("2330", "2026-08-10")
    b = chips.get_institutional("2330", "2026-08-10")
    assert a == b
    assert calls["n"] == 1  # 第二次走快取，不再抓交易所


def test_chip_snapshot_complete(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIPS_CACHE_DIR", str(tmp_path))

    def fake_inst(sid, as_of=None):
        return {
            "date": "2026-08-07",
            "foreign_net": 641660.0,
            "trust_net": 61000.0,
            "dealer_net": 1242950.0,
            "total_net": 1945610.0,
            "foreign_dealer_net": 0.0,
        }

    def fake_margin(sid, as_of=None):
        return {
            "date": "2026-08-07",
            "margin_prev": 29949.0,
            "margin_balance": 29657.0,
            "margin_chg": -292.0,
            "short_prev": 38.0,
            "short_balance": 33.0,
            "short_chg": -5.0,
        }

    monkeypatch.setattr(chips, "get_institutional", fake_inst)
    monkeypatch.setattr(chips, "get_margin", fake_margin)
    snap = chips.chip_snapshot("2330", "2026-08-10")
    assert snap["score"] == 90
    assert snap["total_net"] == 1945610.0


def test_chip_snapshot_missing_data(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIPS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(chips, "get_institutional", lambda sid, as_of=None: None)
    snap = chips.chip_snapshot("2330", "2026-08-10")
    assert snap["score"] is None
    assert snap["note"]
