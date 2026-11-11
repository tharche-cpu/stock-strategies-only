// 若設了 NEXT_PUBLIC_API_BASE 就直接打 FastAPI（避開 Next dev proxy 的 socket hang up），
// 否則走 next.config rewrites 代理。長請求如 /api/run 強烈建議走直連。
const BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export type Strategy = {
  id: string;
  name: string;
  description?: string;
  source?: "default" | "manual" | "ai";
  created_at?: string;
  updated_at?: string;
  params: Record<string, any>;
};

export type RunResult = {
  strategy: { id: string; name: string };
  market: { bullish: boolean; close: number | null; ma20: number | null; note: string };
  downgraded: number;
  summary: { total: number; buy: number; watch: number; skip: number; error: number };
  results: any[];
};

export type PerfRecord = {
  signal_date: string;
  stock_id: string;
  name: string;
  entry_close?: any;
  entry_open?: any;
  t5_date?: string;
  t5_close?: any;
  t5_ret?: any;
  t10_date?: string;
  t10_close?: any;
  t10_ret?: any;
  t20_date?: string;
  t20_close?: any;
  t20_ret?: any;
  hit_target?: string;
  hit_stop?: string;
  status?: string;
};

export type PerformanceData = {
  records: PerfRecord[];
  summary: {
    count: number;
    winrate_t20: number | null;
    avg_t20: number | null;
    hit_target: number;
    hit_stop: number;
  } | null;
  error?: string | null;
};

async function jfetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listStrategies: () => jfetch<{ strategies: Strategy[] }>("/api/strategies"),
  getDefaults: () => jfetch<{ params: Record<string, any> }>("/api/strategies/defaults"),
  getStrategy: (id: string) => jfetch<Strategy>(`/api/strategies/${id}`),
  saveStrategy: (s: Partial<Strategy>) =>
    jfetch<Strategy>("/api/strategies", { method: "POST", body: JSON.stringify(s) }),
  deleteStrategy: (id: string) =>
    jfetch<{ ok: boolean }>(`/api/strategies/${id}`, { method: "DELETE" }),
  generateAI: (prompt: string, name?: string) =>
    jfetch<Strategy>("/api/strategies/generate", {
      method: "POST",
      body: JSON.stringify({ prompt, name }),
    }),
  getMarket: () => jfetch<any>("/api/market"),
  getWatchlist: () => jfetch<{ items: any[]; error?: string }>("/api/watchlist"),
  getPerformance: () => jfetch<PerformanceData>("/api/performance"),
  run: (strategy_id: string, limit?: number) =>
    jfetch<RunResult>("/api/run", {
      method: "POST",
      body: JSON.stringify({ strategy_id, limit }),
    }),
};
