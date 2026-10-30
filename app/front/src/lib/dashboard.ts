/** Turn API responses into what the dashboard shows. No rendering here, so it's easy to test. */

import type { AssetTotal, Coverage, Impact, Pair, Score, TrajectoryPoint } from "@/api/client";
import { assetLabel } from "@/lib/format";
import { sortHazards } from "@/lib/hazards";

export type ScoreKind = "scored" | "no_model" | "no_data" | "error";

/** physrisk's negative scores mean there's no result. They must never read as a low score. */
export function scoreKind(score: number): ScoreKind {
  if (score >= 0) return "scored";
  if (score === -1) return "no_model";
  if (score === -2) return "no_data";
  return "error";
}

export const SCORE_NOTES: Record<Exclude<ScoreKind, "scored">, string> = {
  no_model: "No model",
  no_data: "No data",
  error: "Error",
};

export interface AssetRow {
  rowNum: number;
  label: string;
  total: number | null;
  /** The same asset's historical loss, over only the hazards this scenario has. */
  historical: number | null;
  aal: Record<string, number | null>;
  scores: Record<string, Score>;
}

export function buildRows(
  totals: AssetTotal[],
  impacts: Impact[],
  scores: Score[],
  historical: Impact[],
): AssetRow[] {
  const rows = new Map<number, AssetRow>(
    totals.map((total) => [
      total.row_num,
      {
        rowNum: total.row_num,
        label: assetLabel(total),
        total: total.total_aal,
        historical: null,
        aal: {},
        scores: {},
      },
    ]),
  );
  for (const impact of impacts) {
    const row = rows.get(impact.row_num);
    if (row) row.aal[impact.hazard] = (row.aal[impact.hazard] ?? 0) + (impact.aal ?? 0);
  }
  for (const score of scores) {
    const row = rows.get(score.row_num);
    if (row) row.scores[score.hazard] = score;
  }
  for (const impact of historical) {
    const row = rows.get(impact.row_num);
    if (row && impact.hazard in row.aal) {
      row.historical = (row.historical ?? 0) + (impact.aal ?? 0);
    }
  }
  return [...rows.values()];
}

export const byTotalDescending = (a: AssetRow, b: AssetRow) =>
  (b.total ?? -1) - (a.total ?? -1) || a.rowNum - b.rowNum;

export interface HazardColumns {
  /** Hazards with a real score for at least one asset. */
  scored: string[];
  /** Hazards where every asset has no model. */
  noModel: string[];
  /** Hazards where every asset has no data. */
  noData: string[];
}

export function hazardColumns(rows: AssetRow[]): HazardColumns {
  const kinds = new Map<string, Set<ScoreKind>>();
  for (const row of rows) {
    for (const [hazard, score] of Object.entries(row.scores)) {
      if (!kinds.has(hazard)) kinds.set(hazard, new Set());
      kinds.get(hazard)!.add(scoreKind(score.score));
    }
  }
  const all = sortHazards(kinds.keys());
  const only = (hazard: string, kind: ScoreKind) =>
    kinds.get(hazard)!.size === 1 && kinds.get(hazard)!.has(kind);
  const noModel = all.filter((hazard) => only(hazard, "no_model"));
  const noData = all.filter((hazard) => only(hazard, "no_data"));
  return {
    scored: all.filter((hazard) => !noModel.includes(hazard) && !noData.includes(hazard)),
    noModel,
    noData,
  };
}

const samePair = (a: Pair, b: Pair) => a.scenario === b.scenario && a.year === b.year;

export const pointFor = (trajectory: TrajectoryPoint[], pair: Pair) =>
  trajectory.find((point) => samePair(point, pair));

export const missingHazards = (coverage: Coverage[], pair: Pair) =>
  sortHazards(coverage.filter((c) => samePair(c, pair) && !c.covered).map((c) => c.hazard));

export const scenariosOf = (trajectory: TrajectoryPoint[]) => [
  ...new Set(trajectory.filter((p) => p.year !== null).map((p) => p.scenario)),
];

export const yearsOf = (trajectory: TrajectoryPoint[], scenario: string) =>
  trajectory
    .filter((p) => p.scenario === scenario && p.year !== null)
    .map((p) => p.year as number)
    .sort((a, b) => a - b);

const PREFERRED_YEAR = 2050;

/** Start on the scenario with the most hazards, at the year nearest mid-century. */
export function defaultPair(trajectory: TrajectoryPoint[]): Pair | null {
  const candidates = trajectory.filter((p) => p.year !== null);
  if (candidates.length === 0) return null;
  const best = candidates.reduce((a, b) => (b.hazards > a.hazards ? b : a));
  const years = yearsOf(trajectory, best.scenario);
  const year = years.reduce((a, b) =>
    Math.abs(b - PREFERRED_YEAR) < Math.abs(a - PREFERRED_YEAR) ? b : a,
  );
  return { scenario: best.scenario, year };
}

export interface TrajectoryDatum {
  year: number;
  historical: number | null;
  [scenario: string]: number | null;
}

/** Shared-hazard means by year, because only those can be compared across scenarios. */
export function trajectorySeries(trajectory: TrajectoryPoint[]): {
  scenarios: string[];
  data: TrajectoryDatum[];
} {
  const baseline = trajectory.find((p) => p.year === null)?.mean_shared_aal ?? null;
  const withResults = trajectory.filter((p) => p.year !== null && p.mean_shared_aal !== null);
  const scenarios = [...new Set(withResults.map((p) => p.scenario))];
  const years = [...new Set(withResults.map((p) => p.year as number))].sort((a, b) => a - b);
  const data = years.map((year) => {
    const datum: TrajectoryDatum = { year, historical: baseline };
    for (const scenario of scenarios) {
      const point = withResults.find((p) => p.scenario === scenario && p.year === year);
      datum[scenario] = point?.mean_shared_aal ?? null;
    }
    return datum;
  });
  return { scenarios, data };
}

export const TOP_ASSETS = 15;

/** The rows the bar chart draws: the largest losses, as data its stacks can read. */
export function barData(rows: AssetRow[]) {
  return [...rows]
    .sort(byTotalDescending)
    .slice(0, TOP_ASSETS)
    .map((row) => {
      const present = sortHazards(
        Object.keys(row.aal).filter((hazard) => (row.aal[hazard] ?? 0) > 0),
      );
      return {
        rowNum: row.rowNum,
        label: row.label,
        total: row.total,
        historical: row.historical,
        /** Where the total's label goes: past whichever of the bar and the marker reaches further. */
        labelEnd: Math.max(row.total ?? 0, row.historical ?? 0),
        lastHazard: present[present.length - 1] ?? null,
        ...row.aal,
      };
    });
}

/** Share of assessed assets whose building type is our assumption, from 0 to 1. */
export const assumedShare = (assessable: number, assumed: number) =>
  assessable === 0 ? 0 : assumed / assessable;
