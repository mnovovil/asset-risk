import { useEffect, useState } from "react";

import {
  ApiError,
  getAssets,
  getCoverage,
  getImpacts,
  getScores,
  getSummary,
  getTotals,
  getTrajectory,
  type Asset,
  type AssetTotal,
  type Coverage,
  type Impact,
  type Pair,
  type Score,
  type Summary,
  type TrajectoryPoint,
} from "@/api/client";

export interface RunData {
  summary: Summary;
  assets: Asset[];
  trajectory: TrajectoryPoint[];
  coverage: Coverage[];
  historical: Impact[];
}

export interface PairData {
  totals: AssetTotal[];
  impacts: Impact[];
  scores: Score[];
}

const HISTORICAL: Pair = { scenario: "historical", year: null };

const messageOf = (error: unknown) =>
  error instanceof ApiError ? error.message : "The results couldn't be loaded.";

/** What stays the same for a run: loaded once. */
export function useRunData(runId: string) {
  const [data, setData] = useState<RunData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      getSummary(runId, signal),
      getAssets(runId, signal),
      getTrajectory(runId, signal),
      getCoverage(runId, signal),
      getImpacts(runId, HISTORICAL, signal),
    ])
      .then(([summary, assets, trajectory, coverage, historical]) =>
        setData({ summary, assets, trajectory, coverage, historical }),
      )
      .catch((e: unknown) => {
        if (!signal.aborted) setError(messageOf(e));
      });
    return () => controller.abort();
  }, [runId]);

  return { data, error };
}

/** Results for the selected scenario and year. The last ones stay on screen while new ones load. */
export function usePairData(runId: string, pair: Pair | null) {
  const [data, setData] = useState<PairData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scenario = pair?.scenario;
  const year = pair?.year;

  useEffect(() => {
    if (scenario === undefined || year === undefined) return;
    const selected: Pair = { scenario, year };
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setError(null);
    Promise.all([
      getTotals(runId, selected, signal),
      getImpacts(runId, selected, signal),
      getScores(runId, selected, signal),
    ])
      .then(([totals, impacts, scores]) => {
        setData({ totals, impacts, scores });
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (signal.aborted) return;
        setError(messageOf(e));
        setLoading(false);
      });
    return () => controller.abort();
  }, [runId, scenario, year]);

  return { data, loading, error };
}
