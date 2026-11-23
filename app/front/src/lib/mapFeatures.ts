/** The map's asset points as GeoJSON. No MapLibre here, so it's testable. */

import type { Asset } from "@/api/client";
import type { AssetRow } from "@/lib/dashboard";
import { assetLabel, money, percent } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { lossBreaks, NO_RESULT_COLOR, scoreColor, totalColor } from "@/lib/mapColors";

/** The "Colour by" value for total annual loss. */
export const COLOR_BY_TOTAL = "total";
/** The "Colour by" value for expected annual loss in money, offered when the run has values. */
export const COLOR_BY_EXPECTED_LOSS = "expected_loss";
// Any other "Colour by" value is a hazard's score.

/** Whether the map is coloured by a loss, ranked into classes, rather than by a hazard's score. */
export const isLossColoring = (colorBy: string) =>
  colorBy === COLOR_BY_TOTAL || colorBy === COLOR_BY_EXPECTED_LOSS;

/** The loss an asset is coloured by: a share of value, or an amount. */
export const lossOf = (row: AssetRow | undefined, colorBy: string): number | null =>
  (colorBy === COLOR_BY_EXPECTED_LOSS ? row?.expectedLoss : row?.total) ?? null;

/** A loss as the map writes it. */
export const formatLoss = (loss: number | null, colorBy: string, currency: string | null) =>
  colorBy === COLOR_BY_EXPECTED_LOSS ? money(loss, currency, true) : percent(loss);

function describe(
  asset: Asset,
  row: AssetRow | undefined,
  colorBy: string,
  currency: string | null,
): string {
  if (!asset.assessable) return "Excluded";
  if (colorBy === COLOR_BY_TOTAL) return `Total annual loss ${percent(row?.total)}`;
  if (colorBy === COLOR_BY_EXPECTED_LOSS) {
    if (row && row.value === null) return "No usable value";
    return `Expected annual loss ${money(row?.expectedLoss, currency, true)}`;
  }
  return `${hazardLabel(colorBy)}: ${row?.scores[colorBy]?.label ?? "No result"}`;
}

/** How the map frames the portfolio when it opens: shared by the dashboard map and thumbnails. */
export const FIT_PADDING_PX = 48;
export const MAX_FIT_ZOOM = 11;

/** The west-south and east-north corners around points, or null when there are none. */
export function boundsOf(
  coordinates: [number, number][],
): [[number, number], [number, number]] | null {
  if (coordinates.length === 0) return null;
  const lons = coordinates.map(([lon]) => lon);
  const lats = coordinates.map(([, lat]) => lat);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}

/** The losses the colour classes are drawn from: assets with a result (and a value) only. */
export const totalsOf = (rows: AssetRow[], colorBy: string = COLOR_BY_TOTAL) =>
  rows.flatMap((row) => {
    const loss = lossOf(row, colorBy);
    return loss === null ? [] : [loss];
  });

/** Assets the map can place: real coordinates only. */
export const placeable = (assets: Asset[]) =>
  assets.filter(
    (a) => a.lat !== null && a.lon !== null && Math.abs(a.lat) <= 90 && Math.abs(a.lon) <= 180,
  );

/**
 * One point per placeable asset. When the run has clusters, the opening view shows only bubbles,
 * so every point but the selected one is marked `zoomedIn` and only shows once the reader zooms in.
 * With no clusters, every point shows at every zoom.
 */
export function toFeatures(
  assets: Asset[],
  rows: AssetRow[],
  colorBy: string,
  selected: number | null,
  dark: boolean,
  ring: string,
  hasClusters: boolean,
  currency: string | null = null,
): GeoJSON.FeatureCollection {
  const byRow = new Map(rows.map((row) => [row.rowNum, row]));
  const breaks = lossBreaks(totalsOf(rows, colorBy));
  const features: GeoJSON.Feature[] = placeable(assets).map((asset) => {
    const row = byRow.get(asset.row_num);
    const loss = lossOf(row, colorBy);
    let color: string | null = null;
    if (row && isLossColoring(colorBy) && loss !== null) {
      color = totalColor(loss, breaks, dark);
    } else if (row && !isLossColoring(colorBy) && row.scores[colorBy]) {
      color = scoreColor(row.scores[colorBy].score, dark);
    }
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [asset.lon as number, asset.lat as number] },
      properties: {
        rowNum: asset.row_num,
        label: assetLabel(asset),
        detail: describe(asset, row, colorBy, currency),
        color: color ?? "rgba(0,0,0,0)",
        ring: color ? ring : NO_RESULT_COLOR,
        radius: asset.row_num === selected ? 9 : 6,
        zoomedIn: hasClusters && asset.row_num !== selected,
      },
    };
  });
  return { type: "FeatureCollection", features };
}
