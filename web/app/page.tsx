"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Strategy, RunResult, PerformanceData } from "@/lib/api";
import { ActionBadge, SourceBadge } from "@/components/ActionBadge";

function RetCell({ v }: { v: any }) {
  if (v == null || v === "") return <td className="py-2 pr-2 text-right text-muted">—</td>;
  const n = Number(v);
  const cls = n >= 0 ? "text-buy" : "text-err";
  return <td className={`py-2 pr-2 text-right font-mono ${cls}`}>{n > 0 ? "+" : ""}{n}%</td>;
}

export default function Dashboard() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [picked, setPicked] = useState<string>("default");
  const [market, setMarket] = useState<any>(null);
  const [watchCount, setWatchCount] = useState<number | null>(null);
  const [perf, setPerf] = useState<PerformanceData | null>(null);
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listStrategies().then((d) => {
      setStrategies(d.strategies);
      if (d.strategies.find((s) => s.id === "default")) setPicked("default");
      else if (d.strategies[0]) setPicked(d.strategies[0].id);
    });
    api.getMarket().then(setMarket).catch(() => setMarket(null));
    api.getWatchlist().then((w) => setWatchCount(w.items?.length ?? 0)).catch(() => setWatchCount(null));
    api.getPerformance().then(setPerf).catch(() => setPerf(null));
  }, []);

  async function doRun() {
    setRunning(true);
    setError(null);
    setRun(null);
    try {
      const r = await api.run(picked);
      setRun(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  const selected = strategies.find((s) => s.id === picked);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted mt-1">選一個策略，按下執行即可掃描 watchlist。</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-xs text-muted">大盤狀態</div>
          {market ? (
            <>
              <div className={"text-2xl font-semibold mt-2 " + (market.bullish ? "text-buy" : "text-err")}>
                {market.bullish ? "🟢 多頭" : "🔴 空頭"}
              </div>
              <div className="text-xs text-muted mt-2 leading-relaxed">{market.note}</div>
            </>
          ) : (
            <div className="text-muted mt-2 text-sm">載入中…</div>
          )}
        </div>
        <div className="card">
          <div className="text-xs text-muted">Watchlist</div>
          <div className="text-2xl font-semibold mt-2">{watchCount ?? "—"} 檔</div>
          <div className="text-xs text-muted mt-2">來自 Google Sheet</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted">可用策略</div>
          <div className="text-2xl font-semibold mt-2">{strategies.length}</div>
          <div className="text-xs text-muted mt-2">
            <Link href="/strategies/ai" className="hover:text-text underline-offset-4 hover:underline">+ AI 生一個</Link>
          </div>
        </div>
      </div>

      {perf && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium">訊號成績單</h2>
            <div className="text-xs text-muted">來源：Google Sheet「Performance」分頁</div>
          </div>
          {perf.error && <div className="text-sm text-err mb-3">讀取失敗：{perf.error}</div>}
          {perf.records.length === 0 && !perf.error ? (
            <div className="text-sm text-muted">「Performance」分頁尚未有紀錄，跑過每日任務後就會開始追蹤。</div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <div className="bg-panel2 border border-line rounded-lg p-3">
                  <div className="text-xs text-muted">完成追蹤</div>
                  <div className="text-2xl font-semibold mt-1">{perf.summary?.count ?? 0}</div>
                  <div className="text-xs text-muted mt-1">
                    {perf.records.filter((r) => String(r.status || "").includes("追蹤")).length} 筆追蹤中
                  </div>
                </div>
                <div className="bg-panel2 border border-line rounded-lg p-3">
                  <div className="text-xs text-muted">T+20 勝率</div>
                  <div className="text-2xl font-semibold mt-1">
                    {perf.summary?.winrate_t20 != null ? `${perf.summary.winrate_t20}%` : "—"}
                  </div>
                </div>
                <div className="bg-panel2 border border-line rounded-lg p-3">
                  <div className="text-xs text-muted">T+20 平均報酬</div>
                  <div className={"text-2xl font-semibold mt-1 " + ((perf.summary?.avg_t20 ?? 0) >= 0 ? "text-buy" : "text-err")}>
                    {perf.summary?.avg_t20 != null ? `${perf.summary.avg_t20}%` : "—"}
                  </div>
                </div>
                <div className="bg-panel2 border border-line rounded-lg p-3">
                  <div className="text-xs text-muted">停利 / 停損</div>
                  <div className="text-2xl font-semibold mt-1">
                    <span className="text-buy">{perf.summary?.hit_target ?? 0}</span>
                    <span className="text-muted text-base mx-1">/</span>
                    <span className="text-err">{perf.summary?.hit_stop ?? 0}</span>
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted border-b border-line">
                      <th className="py-2 pr-3">訊號日</th>
                      <th className="py-2 pr-3">代號</th>
                      <th className="py-2 pr-3">名稱</th>
                      <th className="py-2 pr-3 text-right">進場</th>
                      <th className="py-2 pr-3 text-right">T+5</th>
                      <th className="py-2 pr-3 text-right">T+10</th>
                      <th className="py-2 pr-3 text-right">T+20</th>
                      <th className="py-2 pr-3">停利/損</th>
                      <th className="py-2">狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...perf.records].reverse().map((r) => (
                      <tr key={`${r.signal_date}-${r.stock_id}`} className="border-b border-line">
                        <td className="py-2 pr-3 font-mono">{r.signal_date}</td>
                        <td className="py-2 pr-3 font-mono">{r.stock_id}</td>
                        <td className="py-2 pr-3">{r.name || "—"}</td>
                        <td className="py-2 pr-3 text-right font-mono">{r.entry_open || "—"}</td>
                        <RetCell v={r.t5_ret} />
                        <RetCell v={r.t10_ret} />
                        <RetCell v={r.t20_ret} />
                        <td className="py-2 pr-3">
                          {r.hit_target === "Y" && <span className="badge-buy mr-1">+10%</span>}
                          {r.hit_stop === "Y" && <span className="badge-err">−8%</span>}
                        </td>
                        <td className="py-2">{r.status || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      <div className="card">
        <h2 className="font-medium mb-4">執行今日選股</h2>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
          <div>
            <label className="label">選擇策略</label>
            <select className="input" value={picked} onChange={(e) => setPicked(e.target.value)}>
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>{s.name}（{s.id}）</option>
              ))}
            </select>
            {selected && (
              <div className="flex items-center gap-2 mt-2 text-xs">
                <SourceBadge source={selected.source} />
                <span className="text-muted">{selected.description}</span>
              </div>
            )}
          </div>
          <button onClick={doRun} disabled={running || !picked} className="btn-primary h-10">
            {running ? "執行中…可能要一兩分鐘" : "▶ 執行"}
          </button>
        </div>
        {error && <div className="text-sm text-err mt-3">錯誤：{error}</div>}
      </div>

      {run && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium">執行結果</h2>
            <div className="flex gap-2 text-xs">
              <span className="badge-buy">BUY {run.summary.buy}</span>
              <span className="badge-watch">WATCH {run.summary.watch}</span>
              <span className="badge-skip">SKIP {run.summary.skip}</span>
              {run.summary.error > 0 && <span className="badge-err">ERR {run.summary.error}</span>}
            </div>
          </div>
          <div className="text-xs text-muted mb-3">{run.market.note}</div>
          <div className="space-y-2">
            {run.results.filter((r) => r.action !== "ERROR").map((r) => (
              <div key={r.stock_id} className="bg-panel2 border border-line rounded-lg p-3 flex items-center gap-3">
                <ActionBadge action={r.action} />
                <div className="font-mono w-16">{r.stock_id}</div>
                <div className="flex-1 truncate">
                  <div className="text-sm">{r.name}</div>
                  <div className="text-xs text-muted">
                    {r.components?.tech_signals?.join(" · ") || "—"}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono">{r.signal_score}</div>
                  <div className="text-xs text-muted">
                    勝率 {r.components?.backtest_winrate != null
                      ? `${(r.components.backtest_winrate * 100).toFixed(0)}%` : "—"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
