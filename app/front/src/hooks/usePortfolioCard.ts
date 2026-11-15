import { useEffect, useState } from "react";

import {
  ApiError,
  getOverview,
  getTotals,
  type AssetTotal,
  type Pair,
  type RunOverview,
} from "@/api/client";
import { defaultPair } from "@/lib/dashboard";

export interface PortfolioCardData {
  overview: RunOverview;
  /** The pair the dashboard opens on, or null when the run has no future year at all. */
  pair: Pair | null;
  totals: AssetTotal[];
}

/**
 * A completed run's figures for its card: the overview, then the totals for the pair the
 * dashboard opens on, so the card and the dashboard agree. Loaded once, when `enabled` turns true.
 */
export function usePortfolioCard(runId: string, enabled: boolean) {
  const [data, setData] = useState<PortfolioCardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const { signal } = controller;
    (async () => {
      const overview = await getOverview(runId, signal);
      const pair = defaultPair(overview.trajectory);
      const totals = pair ? await getTotals(runId, pair, signal) : [];
      setData({ overview, pair, totals });
    })().catch((e: unknown) => {
      if (signal.aborted) return;
      setError(e instanceof ApiError ? e.message : "The results couldn't be loaded.");
    });
    return () => controller.abort();
  }, [runId, enabled]);

  return { data, error };
}
