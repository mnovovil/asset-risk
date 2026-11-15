import { describe, expect, it } from "vitest";

import type { AssetTotal, Cluster, MapPoint } from "@/api/client";
import { lossBreaks, NO_RESULT_COLOR, totalColor } from "@/lib/mapColors";
import { BUBBLE_OPACITY, thumbnailFeatures } from "@/lib/thumbnail";

const POINTS: MapPoint[] = [
  { row_num: 1, lat: 40, lon: -4 },
  { row_num: 2, lat: 30, lon: -95 },
  { row_num: 4, lat: 41, lon: -3 },
];

const total = (row_num: number, total_aal: number | null): AssetTotal => ({
  row_num,
  asset_id: `a${row_num}`,
  total_aal,
  shared_aal: total_aal,
  hazards: 3,
});

const TOTALS = [total(1, 0.01), total(2, 0.03), total(4, null)];

const props = (collection: GeoJSON.FeatureCollection) =>
  collection.features.map((f) => f.properties as Record<string, unknown>);

describe("thumbnailFeatures", () => {
  it("without clusters, draws every point, coloured on the same classes as the map", () => {
    const { features, bounds } = thumbnailFeatures(POINTS, [], TOTALS, false, "#fff");
    const breaks = lossBreaks([0.01, 0.03]);
    expect(props(features).map((p) => p.color)).toEqual([
      totalColor(0.01, breaks, false),
      totalColor(0.03, breaks, false),
      "rgba(0,0,0,0)",
    ]);
    expect(props(features).map((p) => p.ring)).toEqual(["#fff", "#fff", NO_RESULT_COLOR]);
    expect(bounds).toEqual([
      [-95, 30],
      [-3, 41],
    ]);
  });

  it("with clusters, draws only the bubbles, as the dashboard map opens", () => {
    const clusters: Cluster[] = [
      {
        cluster_id: 7,
        assets: 2,
        row_nums: [1, 4],
        lat: 40.5,
        lon: -3.5,
        bounds: [-4, 40, -3, 41],
      },
    ];
    const { features, bounds } = thumbnailFeatures(POINTS, clusters, TOTALS, true, "#000");
    expect(features.features).toHaveLength(1);
    const [bubble] = props(features);
    // Only one member has a result, so the bubble takes its colour.
    expect(bubble.color).toBe(totalColor(0.01, lossBreaks([0.01, 0.03]), true));
    expect(bubble.opacity).toBe(BUBBLE_OPACITY);
    expect(features.features[0].geometry).toEqual({ type: "Point", coordinates: [-3.5, 40.5] });
    // Still framed on every asset, not just the bubbles.
    expect(bounds?.[0]).toEqual([-95, 30]);
  });

  it("draws a bubble with no results hollow", () => {
    const clusters: Cluster[] = [
      { cluster_id: 1, assets: 1, row_nums: [4], lat: 41, lon: -3, bounds: [-3, 41, -3, 41] },
    ];
    const [bubble] = props(thumbnailFeatures(POINTS, clusters, TOTALS, false, "#fff").features);
    expect([bubble.color, bubble.ring]).toEqual(["rgba(0,0,0,0)", NO_RESULT_COLOR]);
  });

  it("has no bounds when no asset can be placed", () => {
    expect(thumbnailFeatures([], [], [], false, "#fff").bounds).toBeNull();
  });
});
