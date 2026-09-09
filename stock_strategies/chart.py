"""趨勢/盤整圖渲染（matplotlib → PNG bytes）。

搭配 TA-Lib 指標：ADX 判斷趨勢強度、RSI 判斷超買超賣。
- 圖內文字全部用 ASCII/數字（stock code、ADX、RSI、Close），中文只放 Telegram caption，
  避免 GitHub Actions runner 沒有 CJK 字體時圖片是豆腐塊。
- matplotlib 未安裝 → render_trend_chart 回 None，不影響主流程。
"""
from __future__ import annotations

import io
from typing import Optional

DEFAULT_LOOKBACK = 60


def _cjk_font():
    """抓可用中文字型；找不到回 None（圖就只用英文標籤）。"""
    try:
        from matplotlib import font_manager

        for name in ("Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Noto Sans CJK TC"):
            if any(f.name == name for f in font_manager.fontManager.ttflist):
                return name
    except Exception:
        pass
    return None


def _figsize(n_points: int) -> tuple[float, float]:
    return (9.0, max(5.5, 2.4 + n_points / 60.0))


def render_trend_chart(
    chart: dict,
    title_line: str = "",
    lookback: int = DEFAULT_LOOKBACK,
) -> Optional[bytes]:
    """把一檔的近 N 日指標渲染成 PNG bytes。

    chart 內含（由 evaluate 產生，JSON 安全瞭列）：
      dates: list[str]
      close / ma20 / adx / rsi: list[float]，缺的會略過對應子圖。

    回 PNG bytes；任何異常或資料不足 → None。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt

        import numpy as np

        dates = list(chart.get("dates") or [])
        close = list(chart.get("close") or [])
        if len(dates) < 5 or len(close) < 5:
            return None
        dates = dates[-lookback:]
        close = np.array([np.nan if v is None else float(v) for v in close[-lookback:]])

        def _arr(key):
            raw = chart.get(key)
            if not raw:
                return None
            vals = [np.nan if v is None else float(v) for v in raw[-lookback:]]
            return np.array(vals, dtype=float)

        ma20 = _arr("ma20")
        adx = _arr("adx")
        rsi = _arr("rsi")

        font = _cjk_font()
        if font:
            from matplotlib import rcParams

            rcParams["font.sans-serif"] = [font]

        rows = 2 + (1 if (rsi is not None and adx is not None) else 0)
        fig, axes = plt.subplots(
            rows, 1, figsize=_figsize(len(dates)), dpi=100, sharex=True,
            gridspec_kw={"height_ratios": [2, 1, 1][:rows]},
        )
        if rows == 1:
            axes = [axes]
        ax_px, ax_others = axes[0], axes[1:]

        # 上：收盤價 + MA20
        ax_px.plot(dates, close, color="#1f77b4", linewidth=1.4, label="Close")
        if ma20 is not None:
            ax_px.plot(dates, ma20, color="#ff7f0e", linewidth=1.0, alpha=0.85, label="MA20")
        ax_px.set_title(title_line, fontsize=10)
        ax_px.legend(loc="upper left", fontsize=8, ncol=2)
        ax_px.set_ylabel("Price", fontsize=8)
        ax_px.grid(alpha=0.25)
        ax_px.tick_params(labelsize=7)

        if adx is not None and np.any(~np.isnan(adx)):
            ax_adx = ax_others[0]
            ok_adx = ~np.isnan(adx)
            ax_adx.plot(dates, adx, color="#2ca02c", linewidth=1.2, label="ADX")
            ax_adx.axhline(25, color="#d62728", linewidth=0.8, linestyle="--", alpha=0.7)
            ax_adx.axhline(20, color="#ff7f0e", linewidth=0.8, linestyle=":", alpha=0.8)
            ax_adx.fill_between(dates, adx, 20, where=ok_adx & (adx >= 20),
                                color="#2ca02c", alpha=0.15, interpolate=True)
            ax_adx.text(dates[0], 25.3, "trend(25)", fontsize=6, color="#d62728")
            ax_adx.text(dates[0], 19.3, "range(20)", fontsize=6, color="#ff7f0e")
            ax_adx.set_ylabel("ADX", fontsize=8)
            ax_adx.legend(loc="upper left", fontsize=8, ncol=3)
            ax_adx.grid(alpha=0.25)
            ax_adx.tick_params(labelsize=7)

        if rsi is not None and np.any(~np.isnan(rsi)):
            ax_rsi = ax_others[-1]
            ax_rsi.plot(dates, rsi, color="#9467bd", linewidth=1.2, label="RSI")
            ax_rsi.axhline(70, color="#d62728", linewidth=0.8, linestyle="--", alpha=0.7)
            ax_rsi.axhline(30, color="#2ca02c", linewidth=0.8, linestyle=":", alpha=0.8)
            ax_rsi.fill_between(dates, 70, 30, color="#cccccc", alpha=0.15)
            ax_rsi.text(dates[0], 71.3, "overbought(70)", fontsize=6, color="#d62728")
            ax_rsi.text(dates[0], 28.3, "oversold(30)", fontsize=6, color="#2ca02c")
            ax_rsi.set_ylabel("RSI", fontsize=8)
            ax_rsi.legend(loc="upper left", fontsize=8, ncol=2)
            ax_rsi.grid(alpha=0.25)
            ax_rsi.tick_params(labelsize=7)
            for label in ax_rsi.get_xticklabels():
                label.set_rotation(35)
                label.set_horizontalalignment("right")

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None