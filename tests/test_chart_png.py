"""趨勢/盤整圖（matplotlib PNG）與 Telegram sendPhoto 的測試。"""
import numpy as np
import pandas as pd
import pytest

from stock_strategies import chart, notify
from stock_strategies.evaluate import _chart_payload, _to_native
from stock_strategies.indicators import add_indicators


def _chart_dict(n=70):
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = 100 + np.arange(n) * 0.5
    df = add_indicators(
        pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "high": closes + 1,
                "low": closes - 1,
                "close": closes,
                "volume": [1000000] * n,
            }
        )
    )
    return _chart_payload(df)


def test_render_trend_chart_returns_png():
    png = chart.render_trend_chart(_chart_dict())
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_render_chart_too_short_returns_none():
    assert chart.render_trend_chart({"dates": [], "close": []}) is None
    assert chart.render_trend_chart({"dates": list(range(3)), "close": [1, 2, 3]}) is None


def test_render_chart_without_talib_series_is_ok():
    data = {
        "dates": [f"2026-01-{i:02d}" for i in range(1, 21)],
        "close": [float(i) for i in range(20)],
        "ma20": None, "adx": None, "rsi": None,
    }
    png = chart.render_trend_chart(data)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_cjk_font_detected_or_none():
    font = chart._cjk_font()
    assert font is None or isinstance(font, str)


def test_evaluate_chart_payload_json_safe():
    payload = _chart_dict()
    assert set(payload) == {"dates", "close", "ma20", "adx", "rsi"}
    assert len(payload["dates"]) == 60
    # 必須可被 JSON 序列化（_to_native 後變純 list）
    import json

    json.dumps(_to_native(payload))
    assert all(v is None or isinstance(v, float) for v in payload["close"])


def test_send_telegram_photo_posts_multipart(monkeypatch):
    calls = {}

    class FakeResp:
        ok = True
        text = "ok"

    def fake_post(url, **kw):
        calls["url"] = url
        calls["data"] = kw.get("data")
        calls["files"] = kw.get("files")
        return FakeResp()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    monkeypatch.setattr(notify.requests, "post", fake_post)

    notify.send_telegram_photo("cap", b"\x89PNG\x1a")
    assert calls["url"].endswith("/sendPhoto")
    assert calls["data"]["chat_id"] == "456"
    assert calls["files"]["photo"][0] == "chart.png"


def test_send_telegram_photo_survives_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    monkeypatch.setattr(notify.requests, "post", boom)
    # 不應拋例外（只印 stderr）
    notify.send_telegram_photo("cap", b"\x89PNG\x1a")