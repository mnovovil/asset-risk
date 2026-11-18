/**
 * What a portfolio card's map thumbnail draws: the dashboard map's opening view, coloured by total
 * annual loss. No MapLibre here, so it's testable.
 */

import type { Asset, AssetTotal, Cluster, MapPoint } from "@/api/client";
import { summariseClusters, toBubbles } from "@/lib/clusters";
import { type AssetRow, buildRows } from "@/lib/dashboard";
import { lossBreaks, NO_RESULT_COLOR, totalColor } from "@/lib/mapColors";
import { boundsOf, COLOR_BY_TOTAL, toFeatures, totalsOf } from "@/lib/mapFeatures";

/** As on the dashboard map, so a bubble reads as a group, not as one asset. */
export const BUBBLE_OPACITY = 0.8;
const POINT_RADIUS_PX = 6;

export interface Thumbnail {
  features: GeoJSON.FeatureCollection;
  /** Around every placeable asset, as the dashboard map opens. null when none can be placed. */
  bounds: [[number, number], [number, number]] | null;
}

/**
 * With clusters, the dashboard map opens on its bubbles only, so the thumbnail does too. Without,
 * every asset is a point. Each feature carries its own `color`, `ring`, `radius` and `opacity`, and
 * one with no result is hollow, never coloured as a low loss.
 */
export function thumbnailFeatures(
  points: MapPoint[],
  clusters: Cluster[],
  totals: AssetTotal[],
  dark: boolean,
  ring: string,
): Thumbnail {
  const rows = buildRows(totals, [], [], []);
  const bounds = boundsOf(points.map((p) => [p.lon, p.lat]));

  if (clusters.length > 0) {
    const bubbles = toBubbles(summariseClusters(clusters, [], rows, COLOR_BY_TOTAL, dark), ring);
    for (const feature of bubbles.features) {
      feature.properties = { ...feature.properties, opacity: BUBBLE_OPACITY };
    }
    return { features: bubbles, bounds };
  }

  const byRow = new Map(rows.map((row) => [row.rowNum, row.total]));
  const breaks = lossBreaks(totalsOf(rows));
  return {
    bounds,
    features: {
      type: "FeatureCollection",
      features: points.map((point) => {
        const total = byRow.get(point.row_num) ?? null;
        const color = total === null ? null : totalColor(total, breaks, dark);
        return {
          type: "Feature",
          geometry: { type: "Point", coordinates: [point.lon, point.lat] },
          properties: {
            color: color ?? "rgba(0,0,0,0)",
            ring: color ? ring : NO_RESULT_COLOR,
            radius: POINT_RADIUS_PX,
            opacity: 1,
          },
        };
      }),
    },
  };
}

const withOpacity = (collection: GeoJSON.FeatureCollection, opacity: number) => {
  for (const feature of collection.features) {
    feature.properties = { ...feature.properties, opacity };
  }
  return collection;
};

/**
 * The dashboard map's opening view for any "Colour the map by", as the PDF report draws it: bubbles
 * only when the run has clusters, otherwise every placeable asset. Built from the same features as
 * the live map, so the two can't disagree.
 */
export function mapViewFeatures(
  assets: Asset[],
  clusters: Cluster[],
  rows: AssetRow[],
  colorBy: string,
  dark: boolean,
  ring: string,
): Thumbnail {
  const hasClusters = clusters.length > 0;
  const points = toFeatures(assets, rows, colorBy, null, dark, ring, hasClusters);
  const bounds = boundsOf(
    points.features.map((f) => (f.geometry as GeoJSON.Point).coordinates as [number, number]),
  );
  if (hasClusters) {
    const bubbles = toBubbles(summariseClusters(clusters, assets, rows, colorBy, dark), ring);
    return { features: withOpacity(bubbles, BUBBLE_OPACITY), bounds };
  }
  return { features: withOpacity(points, 1), bounds };
}
