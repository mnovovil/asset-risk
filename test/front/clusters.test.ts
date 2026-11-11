import { describe, expect, it } from "vitest";

import type { Asset, Cluster } from "@/api/client";
import type { AssetRow } from "@/lib/dashboard";
import { bubbleRadius, clusteredRowNums, summariseClusters } from "@/lib/clusters";
import { scoreColor, totalColor } from "@/lib/mapColors";

import { asset } from "./helpers";

const cluster = (cluster_id: number, row_nums: number[]): Cluster => ({
  cluster_id,
  assets: row_nums.length,
  row_nums,
  lat: 40,
  lon: -3,
  bounds: [-3.1, 39.9, -2.9, 40.1],
});

const row = (rowNum: number, total: number | null, scores: Record<string, number> = {}): AssetRow => ({
  rowNum,
  label: `a${rowNum}`,
  total,
  historical: null,
  aal: {},
  scores: Object.fromEntries(
    Object.entries(scores).map(([hazard, score]) => [
      hazard,
      { row_num: rowNum, asset_id: `a${rowNum}`, hazard, score, label: null },
    ]),
  ),
});

const ASSETS = [1, 2, 3, 4].map((n) => asset(n)) as Asset[];

describe("summariseClusters", () => {
  it("averages total loss over members with results only", () => {
    const rows = [row(1, 0.01), row(2, 0.03), row(3, null), row(4, 0.04)];
    const [summary] = summariseClusters([cluster(0, [1, 2, 3])], ASSETS, rows, "total", false);
    expect(summary.withResults).toBe(2);
    expect(summary.count).toBe(3);
    // Coloured on the same scale as the points: up to the portfolio's largest loss.
    expect(summary.color).toBe(totalColor(0.02, 0.04, false));
    expect(summary.detail).toContain("2 of 3 with results");
  });

  it("uses the rounded mean score for a hazard, ignoring no model and no data", () => {
    const rows = [row(1, 0.01, { Wind: 1 }), row(2, 0.01, { Wind: 2 }), row(3, 0.01, { Wind: -1 })];
    const [summary] = summariseClusters([cluster(0, [1, 2, 3])], ASSETS, rows, "Wind", true);
    expect(summary.withResults).toBe(2);
    expect(summary.color).toBe(scoreColor(2, true));
    expect(summary.detail).toContain("mean score Medium");
  });

  it("draws a cluster with no results hollow, never as a low value", () => {
    const rows = [row(1, 0.01, { Wind: -1 }), row(2, 0.01, { Wind: -2 })];
    const [byHazard] = summariseClusters([cluster(0, [1, 2])], ASSETS, rows, "Wind", false);
    expect(byHazard.color).toBeNull();
    expect(byHazard.detail).toBe("No results for these assets");
    const [byTotal] = summariseClusters([cluster(0, [3, 4])], ASSETS, [], "total", false);
    expect(byTotal.color).toBeNull();
  });

  it("counts members with an assumed building type", () => {
    const assets = [asset(1, { type_source: "assumed" }), asset(2)] as Asset[];
    const [summary] = summariseClusters(
      [cluster(0, [1, 2])],
      assets,
      [row(1, 0.01), row(2, 0.01)],
      "total",
      false,
    );
    expect(summary.assumedType).toBe(1);
    expect(summary.detail).toContain("1 assume the default building type");
  });

  it("returns nothing when there are no clusters", () => {
    expect(summariseClusters([], ASSETS, [row(1, 0.01)], "total", false)).toEqual([]);
    expect(clusteredRowNums([]).size).toBe(0);
  });
});

describe("bubbles", () => {
  it("grow with the count, within limits", () => {
    expect(bubbleRadius(1)).toBe(12);
    expect(bubbleRadius(9)).toBeGreaterThan(bubbleRadius(4));
    expect(bubbleRadius(100000)).toBe(36);
  });

  it("know which assets they stand for", () => {
    expect([...clusteredRowNums([cluster(0, [1, 2]), cluster(1, [5])])]).toEqual([1, 2, 5]);
  });
});
