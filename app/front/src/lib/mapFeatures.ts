/** The map's asset points as GeoJSON. No MapLibre here, so it's testable. */

import type { Asset } from "@/api/client";
import type { AssetRow } from "@/lib/dashboard";
import { assetLabel, percent } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { NO_RESULT_COLOR, scoreColor, totalColor } from "@/lib/mapColors";

/** The "Colour by" value for total annual loss. Any other value is a hazard. */
export const COLOR_BY_TOTAL = "total";

function describe(asset: Asset, row: AssetRow | undefined, colorBy: string): string {
  if (!asset.assessable) return "Excluded";
  if (colorBy === COLOR_BY_TOTAL) return `Total annual loss ${percent(row?.total)}`;
  return `${hazardLabel(colorBy)}: ${row?.scores[colorBy]?.label ?? "No result"}`;
}

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
): GeoJSON.FeatureCollection {
  const byRow = new Map(rows.map((row) => [row.rowNum, row]));
  const max = Math.max(0, ...rows.map((row) => row.total ?? 0));
  const features: GeoJSON.Feature[] = placeable(assets).map((asset) => {
    const row = byRow.get(asset.row_num);
    let color: string | null = null;
    if (row && colorBy === COLOR_BY_TOTAL && row.total !== null) {
      color = totalColor(row.total, max, dark);
    } else if (row && colorBy !== COLOR_BY_TOTAL && row.scores[colorBy]) {
      color = scoreColor(row.scores[colorBy].score, dark);
    }
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [asset.lon as number, asset.lat as number] },
      properties: {
        rowNum: asset.row_num,
        label: assetLabel(asset),
        detail: describe(asset, row, colorBy),
        color: color ?? "rgba(0,0,0,0)",
        ring: color ? ring : NO_RESULT_COLOR,
        radius: asset.row_num === selected ? 9 : 6,
        zoomedIn: hasClusters && asset.row_num !== selected,
      },
    };
  });
  return { type: "FeatureCollection", features };
}
