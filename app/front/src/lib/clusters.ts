/** Summarise each DBSCAN cluster's members for the map's bubbles. No rendering, so it's testable. */

import type { Asset, Cluster } from "@/api/client";
import { type AssetRow, scoreKind } from "@/lib/dashboard";
import { percent } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { lossBreaks, SCORE_LABELS, scoreColor, totalColor } from "@/lib/mapColors";
import { COLOR_BY_TOTAL, totalsOf } from "@/lib/mapFeatures";

const MIN_RADIUS_PX = 12;
const MAX_RADIUS_PX = 36;

export interface ClusterSummary {
  clusterId: number;
  lat: number;
  lon: number;
  /** West, south, east, north. East is past 180 for a cluster across the antimeridian. */
  bounds: [number, number, number, number];
  count: number;
  /** Members with a result for what the map is coloured by. Only these make up the colour. */
  withResults: number;
  /** Members whose building type is the default, because Overture didn't say. */
  assumedType: number;
  /** null when no member has a result: drawn hollow, never as a low value. */
  color: string | null;
  radius: number;
  detail: string;
}

const mean = (values: number[]) => values.reduce((sum, v) => sum + v, 0) / values.length;

/** Area grows with the asset count, so a bubble twice the size isn't read as four times as many. */
export const bubbleRadius = (count: number) =>
  Math.min(MAX_RADIUS_PX, MIN_RADIUS_PX + 2 * (Math.sqrt(count) - 1));

/**
 * Equal-weighted means over the members that have a result, like the portfolio's figures. Members
 * with no model, no data or no result are counted apart, never as a low value.
 */
export function summariseClusters(
  clusters: Cluster[],
  assets: Asset[],
  rows: AssetRow[],
  colorBy: string,
  dark: boolean,
): ClusterSummary[] {
  const byRow = new Map(rows.map((row) => [row.rowNum, row]));
  const assumed = new Set(
    assets.filter((a) => a.assessable && a.type_source === "assumed").map((a) => a.row_num),
  );
  // The points' classes, so a bubble and its assets read on one scale.
  const breaks = lossBreaks(totalsOf(rows));

  return clusters.map((cluster) => {
    const members = cluster.row_nums.map((rowNum) => byRow.get(rowNum));
    let color: string | null = null;
    let value: string;
    let withResults: number;
    if (colorBy === COLOR_BY_TOTAL) {
      const totals = members.flatMap((row) => (row?.total == null ? [] : [row.total]));
      withResults = totals.length;
      const average = totals.length ? mean(totals) : null;
      if (average !== null) color = totalColor(average, breaks, dark);
      value = `Mean total annual loss ${percent(average)}`;
    } else {
      const scores = members.flatMap((row) => {
        const score = row?.scores[colorBy]?.score;
        return score !== undefined && scoreKind(score) === "scored" ? [score] : [];
      });
      withResults = scores.length;
      const average = scores.length ? Math.round(mean(scores)) : null;
      if (average !== null) color = scoreColor(average, dark);
      value = `${hazardLabel(colorBy)}: mean score ${
        average === null ? "–" : SCORE_LABELS[Math.min(average, SCORE_LABELS.length - 1)]
      }`;
    }
    const assumedType = cluster.row_nums.filter((rowNum) => assumed.has(rowNum)).length;
    const parts = [
      withResults
        ? `${value} (${withResults} of ${cluster.assets} with results)`
        : "No results for these assets",
    ];
    if (assumedType) parts.push(`${assumedType} assume the default building type`);
    const [west, south, east, north] = cluster.bounds;
    return {
      clusterId: cluster.cluster_id,
      lat: cluster.lat,
      lon: cluster.lon,
      bounds: [west, south, east, north],
      count: cluster.assets,
      withResults,
      assumedType,
      color,
      radius: bubbleRadius(cluster.assets),
      detail: parts.join(" · "),
    };
  });
}

/** Assets drawn as part of a bubble when zoomed out. */
export const clusteredRowNums = (clusters: Cluster[]) =>
  new Set(clusters.flatMap((cluster) => cluster.row_nums));
