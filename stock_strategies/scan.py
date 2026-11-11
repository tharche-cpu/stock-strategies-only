"""全市場 BUY 掃描：以 20 日均成交金額排名選出流動性前 N 檔，逐檔跑完整
evaluate，把符合 BUY 條件的寫進 Google Sheet 「BUY掃描」分頁。

流程：
  A) 候選宇宙 = TaiwanStockInfo 上市+上櫃一般股（排除興櫃／ETF／權證）
  B) 對每檔抓近 60 日股價（parquet 快取）算 20 日均成交金額 → 排名（可斷點續跑）
  C) 取前 N 檔逐檔 evaluate（結果存本地 JSONL，可續跑）
  D) BUY 結果寫入試算表「BUY掃描」分頁（同一天重跑會覆蓋當日列，不重複）

執行：
  uv run python -m stock_strategies.scan --pool-size 200
  uv run python -m stock_strategies.scan --scan-only            # 跳過 bootstrap，用上次排名
  uv run python -m stock_strategies.scan --bootstrap-only       # 只建排名不評分
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutTimeout
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .cache import _cache_dir, fetch_finmind_cached
from .datasources import get_stock_info
from .evaluate import evaluate
from .loader import get_strategy

# 名稱黑名單：ETF/ETN/權證/受益證券等非一般股
_EXCLUDE_NAME_TOKENS = ("ETF", "ETN", "權證", "受益證券", "特別股")

SCAN_BOARDS = ("twse", "tpex")
DEFAULT_POOL_SIZE = 200
BOOTSTRAP_DAYS = 60          # 抓 60 日就算得出 20 日均成交金額
SAVE_EVERY = 50              # 每 N 檔存一次 bootstrap 進度
BOOTSTRAP_WORKERS = 8        # bootstrap 並行抓股數
BOOTSTRAP_CODE_TIMEOUT = 20  # 單檔護欄秒；超過就視為無資料（背景請求續跑自行結束）
EVAL_WORKERS = 5             # evaluate 並行數


def common_stock_universe() -> pd.DataFrame:
    """上市+上櫃一般股候選宇宙（不回傳興櫃／ETF／權證）。"""
    info = get_stock_info()
    if info.empty:
        return pd.DataFrame(columns=["stock_id", "stock_name", "market_type"])
    info = info[info["market_type"].isin(SCAN_BOARDS)].copy()
    name = info["stock_name"].fillna("").astype(str)
    mask = ~name.apply(lambda n: any(t in n.upper() for t in _EXCLUDE_NAME_TOKENS))
    info = info[mask]
    info = info[info["stock_id"].astype(str).str.match(r"^\d{4,6}$")]
    return info.drop_duplicates(subset=["stock_id"]).reset_index(drop=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _progress_path() -> Path:
    return _cache_dir() / "scan_turnover_progress.parquet"


def _load_progress() -> pd.DataFrame:
    p = _progress_path()
    if not p.exists():
        return pd.DataFrame(
            columns=["stock_id", "avg_turnover_20d", "rows", "max_date", "fetched_at"]
        )
    try:
        return pd.read_parquet(p)
    except Exception:
        return pd.DataFrame(
            columns=["stock_id", "avg_turnover_20d", "rows", "max_date", "fetched_at"]
        )


def _save_progress(df: pd.DataFrame) -> None:
    p = _progress_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def _stock_turnover(code: str):
    """回 {avg_turnover_20d, rows, max_date}；抓不到回 None。

    bootstrap 只用來算成交金額排名，不走 twstock 備援（避免空回股票拖慢）。
    """
    try:
        start = (datetime.now() - timedelta(days=BOOTSTRAP_DAYS)).strftime("%Y-%m-%d")
        px = fetch_finmind_cached("TaiwanStockPrice", code, start, timeout=6)
    except Exception:
        return None
    if "turnover" not in px.columns and "Trading_money" in px.columns:
        px = px.rename(columns={"Trading_money": "turnover"})
    if "turnover" not in px.columns:
        return None
    tv = pd.to_numeric(px["turnover"], errors="coerce").dropna()
    if len(tv) == 0:
        return None
    last = tv.iloc[-20:]
    return {
        "avg_turnover_20d": float(last.mean()),
        "rows": int(len(px)),
        "max_date": str(pd.to_datetime(px["date"]).max().date()),
    }


def bootstrap_turnover(
    codes: list[str],
    refresh: bool = False,
    save_every: int = SAVE_EVERY,
) -> pd.DataFrame:
    """抓候選股價並累計成交金額排名（parquet 進度檔，可斷點續跑）。"""
    old = _load_progress()
    done = set() if refresh else set(str(c) for c in old["stock_id"])
    out = old[old["stock_id"].isin(codes)].copy() if not refresh else pd.DataFrame()
    pending = [c for c in codes if c not in done]
    print(
        f"[bootstrap] 候選 {len(codes)} 檔，已快取 {len(done)}，待抓 {len(pending)}",
        flush=True,
    )

    new_rows: list[dict] = []
    codes_dead = {}
    with ThreadPoolExecutor(max_workers=BOOTSTRAP_WORKERS) as pool:
        futures = {}
        for idx, code in enumerate(pending):
            futures[pool.submit(_stock_turnover, code)] = (idx, code)

        done = 0
        for fut in as_completed(futures):
            idx, code = futures[fut]
            try:
                r = fut.result(timeout=BOOTSTRAP_CODE_TIMEOUT)
            except FutTimeout:
                r = None
            except Exception:
                r = None
            if r is None:
                r = {"avg_turnover_20d": None, "rows": 0, "max_date": None}
            codes_dead[idx] = r
            done += 1
            if done % save_every == 0 or done == len(pending):
                idxs = sorted(codes_dead)
                rows = [
                    {"stock_id": pending[i], "fetched_at": _now_iso(), **codes_dead[i]}
                    for i in idxs
                ]
                out = pd.concat(
                    [out, pd.DataFrame(rows)], ignore_index=True
                ).drop_duplicates(subset=["stock_id"])
                _save_progress(out)
                codes_dead = {}
                print(f"  [bootstrap] {done}/{len(pending)}，最新 {pending[idxs[-1]]}", flush=True)
    _save_progress(out)
    print(f"[bootstrap] 完成，共 {len(out)} 檔有排名資料", flush=True)
    return out


def top_pool(
    progress: pd.DataFrame,
    n: int = DEFAULT_POOL_SIZE,
) -> list[str]:
    """依 20 日均成交金額取前 N；無成交金額的排最後。"""
    p = progress.copy()
    p["avg_turnover_20d"] = pd.to_numeric(p["avg_turnover_20d"], errors="coerce")
    p = p.sort_values("avg_turnover_20d", ascending=False, na_position="last")
    return [str(c) for c in p["stock_id"].head(n)]


def _results_path(strategy_id: str) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return _cache_dir() / f"scan_results_{strategy_id}_{today}.jsonl"


def _load_scan_results(strategy_id: str) -> list[dict]:
    p = _results_path(strategy_id)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _append_scan_row(rec: dict, strategy_id: str) -> None:
    p = _results_path(strategy_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_buy_scan(
    pool_names: list[tuple[str, str]],
    strategy_id: str = "default",
    limit: int | None = None,
) -> list[dict]:
    """並行 evaluate（EVAL_WORKERS 個執行緒）；命中的都記進當日 JSONL。

    回傳全結果、順序與池一致；ERROR 列不算「已完成」——下次重跑會重新評估。
    """
    strategy = get_strategy(strategy_id)
    done = {
        str(r.get("stock_id"))
        for r in _load_scan_results(strategy_id)
        if r.get("action") != "ERROR"
    }
    results: list[dict | None] = [None] * len(pool_names)
    print(f"[scan] 策略={strategy_id or 'default'}，池 {len(pool_names)} 檔，已完成 {len(done)}", flush=True)

    pending = [
        (i, str(code), str(name))
        for i, (code, name) in enumerate(pool_names, 1)
        if str(code) not in done and (limit is None or i <= limit)
    ]
    append_lock = threading.Lock()

    def _eval_one(item: tuple[int, str, str]) -> tuple[int, str, str, dict]:
        i, code, name = item
        try:
            r = evaluate(code, name, strategy=strategy)
        except Exception as e:  # evaluate 內部大多自吞，這裡當最後防線
            r = {"stock_id": code, "name": name, "action": "ERROR",
                 "signal_score": None, "risk_notes": [f"{type(e).__name__}: {e}"]}
        if not r:
            r = {"stock_id": code, "name": name, "action": "ERROR",
                 "signal_score": None, "risk_notes": ["evaluate 回 None"]}
        return i, code, name, r

    with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as pool:
        futures = [pool.submit(_eval_one, item) for item in pending]
        for fut in as_completed(futures):
            i, code, name, r = fut.result()
            results[i - 1] = r
            with append_lock:
                _append_scan_row(r, strategy_id)
            if i % 25 == 0 or i == len(pool_names):
                print(
                    f"  [scan] {i}/{len(pool_names)} {code} {name} → {r.get('action')} "
                    f"分數 {r.get('signal_score')}",
                    flush=True,
                )
    return [r for r in results if r]


def main() -> None:
    ap = argparse.ArgumentParser(description="全市場 BUY 掃描（成交金額前 N 池）")
    ap.add_argument("--strategy", default="default")
    ap.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    ap.add_argument("--limit", type=int, default=None,
                    help="只掃前 N 檔（debug 用）")
    ap.add_argument("--bootstrap-only", action="store_true")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--refresh-bootstrap", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    args = ap.parse_args()

    universe = common_stock_universe()
    print(f"[universe] 一般股候選 {len(universe)} 檔（上市+上櫃）", flush=True)
    if universe.empty:
        print("候選宇宙為空，結束。")
        sys.exit(1)

    if args.bootstrap_only:
        progress = bootstrap_turnover(
            [str(c) for c in universe["stock_id"]], refresh=args.refresh_bootstrap
        )
        pool = top_pool(progress, args.pool_size)
        print("成交金額前 {} 檔：{}".format(args.pool_size, ", ".join(pool)))
        return

    if args.scan_only:
        progress = _load_progress()
    else:
        print("[step1] 建成交金額排名…", flush=True)
        progress = bootstrap_turnover(
            [str(c) for c in universe["stock_id"]], refresh=args.refresh_bootstrap
        )

    pool = top_pool(progress, args.pool_size)
    print(f"[pool] 成交金額前 {len(pool)} 檔：{', '.join(pool)}", flush=True)

    name_map = dict(zip(universe["stock_id"].astype(str), universe["stock_name"].astype(str)))
    pool_names = [(c, name_map.get(c, "")) for c in pool]

    results = run_buy_scan(pool_names, strategy_id=args.strategy, limit=args.limit)
    buys = [r for r in results if r.get("action") == "BUY"]
    print(
        f"[done] 掃描 {len(results)} 檔 → BUY {len(buys)} 檔",
        flush=True,
    )
    for r in buys:
        print(f"  BUY {r['stock_id']} {r.get('name', '')} 分數 {r.get('signal_score')}", flush=True)

    if not args.no_sheet and buys:
        from .sheet import write_scan_tab

        write_scan_tab(buys, strategy_id=args.strategy)
        print(f"[sheet] 已寫入 BUY掃描 分頁（{len(buys)} 列）", flush=True)


if __name__ == "__main__":
    main()