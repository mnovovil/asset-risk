/** Turn API responses into what the dashboard shows. No rendering here, so it's easy to test. */

import type {
  AssetDetail,
  AssetTotal,
  Coverage,
  Impact,
  Pair,
  Score,
  TrajectoryPoint,
} from "@/api/client";
import { assetLabel, scenarioLabel } from "@/lib/format";
import { hazardLabel, sortHazards } from "@/lib/hazards";

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

/**
 * physrisk's historical baseline: present-day risk, which it treats as the year 2025. It comes back
 * with every request, with impacts but no scores, and is stored with no year.
 */
export const BASELINE: Pair = { scenario: "historical", year: null };
export const BASELINE_LABEL = "Today (baseline)";

export const isBaseline = (pair: Pair | null) => pair?.scenario === BASELINE.scenario;

/** Whether the baseline can be shown on its own: it has results for at least one asset. */
export const hasBaseline = (trajectory: TrajectoryPoint[]) =>
  trajectory.some((p) => samePair(p, BASELINE) && p.assets > 0);

export const pairLabel = (pair: Pair) =>
  isBaseline(pair) ? BASELINE_LABEL : `${scenarioLabel(pair.scenario)}, ${pair.year}`;

/** Hazards with an annual loss for any asset: the baseline's columns, as it has no scores. */
export const lossHazards = (rows: AssetRow[]) =>
  sortHazards(rows.flatMap((row) => Object.keys(row.aal)));

export const scenariosOf = (trajectory: TrajectoryPoint[]) => [
  ...new Set(trajectory.filter((p) => p.year !== null).map((p) => p.scenario)),
];

/**
 * A scenario's years, leaving out any with no results for any asset: physrisk can return scores
 * but no losses for a year, as older runs that asked for 2025 show. A scenario with no results at
 * all keeps every year, and the Scenario filter marks it "(no data)".
 */
export const yearsOf = (trajectory: TrajectoryPoint[], scenario: string) => {
  const points = trajectory.filter((p) => p.scenario === scenario && p.year !== null);
  const withResults = points.filter((p) => p.assets > 0);
  return (withResults.length ? withResults : points)
    .map((p) => p.year as number)
    .sort((a, b) => a - b);
};

const PREFERRED_YEAR = 2050;

/** The year nearest mid-century, or undefined when there are none. */
export const preferredYear = (years: number[]) =>
  years.length
    ? years.reduce((a, b) => (Math.abs(b - PREFERRED_YEAR) < Math.abs(a - PREFERRED_YEAR) ? b : a))
    : undefined;

/** Start on the scenario with the most hazards, at the year nearest mid-century. */
export function defaultPair(trajectory: TrajectoryPoint[]): Pair | null {
  const candidates = trajectory.filter((p) => p.year !== null);
  if (candidates.length === 0) return null;
  const best = candidates.reduce((a, b) => (b.hazards > a.hazards ? b : a));
  const year = preferredYear(yearsOf(trajectory, best.scenario)) as number;
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

export type AssetMetric = "loss" | "score";

export interface AssetChartOption {
  key: string;
  metric: AssetMetric;
  hazard: string;
  label: string;
}

const METRIC_LABELS: Record<AssetMetric, string> = { loss: "Annual loss", score: "Score" };

/** The charts one asset can show: annual loss per hazard, then score per hazard. */
export function assetChartOptions(asset: Pick<AssetDetail, "impacts" | "scores">): AssetChartOption[] {
  const option = (metric: AssetMetric) => (hazard: string) => ({
    key: `${metric}:${hazard}`,
    metric,
    hazard,
    label: `${METRIC_LABELS[metric]} — ${hazardLabel(hazard)}`,
  });
  return [
    ...sortHazards(asset.impacts.map((i) => i.hazard)).map(option("loss")),
    ...sortHazards(asset.scores.map((s) => s.hazard)).map(option("score")),
  ];
}

/** A scenario and year whose score is not a value: no model, no data or an error. */
export interface ScoreNote {
  scenario: string;
  year: number;
  kind: Exclude<ScoreKind, "scored">;
}

export interface AssetSeries {
  /** Scenarios with at least one value to draw, in the run's order. */
  scenarios: string[];
  data: TrajectoryDatum[];
  /** The baseline's annual loss, drawn flat for reference. Always null for scores. */
  baseline: number | null;
  /** Run scenarios with nothing at all for this hazard: no line, and no note below. */
  missingScenarios: string[];
  notes: ScoreNote[];
}

const HIGHEST_SCORE = 4;

/**
 * One asset's annual loss or score for one hazard, by year and scenario. A missing or null result
 * stays null, so the chart leaves a gap rather than drawing a zero. physrisk scores scenarios only,
 * so a score has no baseline, and its negative scores become notes, never points.
 */
export function assetSeries(
  asset: Pick<AssetDetail, "impacts" | "scores">,
  metric: AssetMetric,
  hazard: string,
  runScenarios: string[],
): AssetSeries {
  const values = new Map<string, number | null>();
  const keyOf = (scenario: string, year: number | null) => `${scenario}|${year}`;
  const notes: ScoreNote[] = [];
  let baseline: number | null = null;
  const seen = new Set<string>();

  if (metric === "loss") {
    for (const impact of asset.impacts) {
      if (impact.hazard !== hazard) continue;
      // Several impact types add up; only when every one is missing is the result missing.
      const key = keyOf(impact.scenario, impact.year);
      const sum = values.get(key) ?? null;
      values.set(key, impact.aal === null ? sum : (sum ?? 0) + impact.aal);
      if (impact.year === null) baseline = values.get(key) ?? null;
      else seen.add(impact.scenario);
    }
  } else {
    for (const score of asset.scores) {
      if (score.hazard !== hazard || score.year === null) continue;
      seen.add(score.scenario);
      const kind = scoreKind(score.score);
      if (kind === "scored") {
        values.set(keyOf(score.scenario, score.year), Math.min(score.score, HIGHEST_SCORE));
      } else {
        notes.push({ scenario: score.scenario, year: score.year, kind });
      }
    }
  }

  const order = [...new Set([...runScenarios, ...seen])];
  const points = [...values.entries()]
    .map(([key, value]) => {
      const [scenario, year] = key.split("|");
      return { scenario, year: year === "null" ? null : Number(year), value };
    })
    .filter((p): p is { scenario: string; year: number; value: number | null } => p.year !== null);
  const years = [...new Set(points.map((p) => p.year))].sort((a, b) => a - b);
  const scenarios = order.filter((scenario) =>
    points.some((p) => p.scenario === scenario && p.value !== null),
  );
  const data = years.map((year) => {
    const datum: TrajectoryDatum = { year, historical: baseline };
    for (const scenario of scenarios) {
      datum[scenario] = values.get(keyOf(scenario, year)) ?? null;
    }
    return datum;
  });
  const rank = (scenario: string) => order.indexOf(scenario);
  notes.sort((a, b) => rank(a.scenario) - rank(b.scenario) || a.year - b.year);
  return {
    scenarios,
    data,
    baseline,
    missingScenarios: runScenarios.filter(
      (scenario) => !scenarios.includes(scenario) && !notes.some((n) => n.scenario === scenario),
    ),
    notes,
  };
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
