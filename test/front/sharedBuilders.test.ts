import { describe, expect, it } from "vitest";

import type { Asset, Cluster } from "@/api/client";
import { type AssetRow, kpiItems, typeSourceCounts } from "@/lib/dashboard";
import { NO_RESULT_COLOR, ramp, SCORE_LABELS, scoreColor } from "@/lib/mapColors";
import { mapLegend } from "@/lib/mapLegend";
import { COLOR_BY_TOTAL } from "@/lib/mapFeatures";
import { BUBBLE_OPACITY, mapViewFeatures } from "@/lib/thumbnail";

import { ASSETS, asset, SUMMARY, TRAJECTORY } from "./helpers";

const row = (rowNum: number, total: number | null, overrides: Partial<AssetRow> = {}): AssetRow => ({
  rowNum,
  label: `asset-${rowNum}`,
  total,
  historical: null,
  aal: {},
  scores: {},
  value: null,
  expectedLoss: null,
  ...overrides,
});

const props = (collection: GeoJSON.FeatureCollection) =>
  collection.features.map((f) => f.properties as Record<string, unknown>);

describe("kpiItems", () => {
  it("gives the four headline figures, comparing with history on the same hazards", () => {
    const rows = [row(1, 0.02, { historical: 0.01 }), row(2, 0.03, { historical: 0.03 })];
    const items = kpiItems(SUMMARY, TRAJECTORY[4], rows, false);
    expect(items.map((i) => i.label)).toEqual([
      "Mean annual loss, equal-weighted",
      "Assets assessed",
      "Assets excluded",
      "Building type assumed",
    ]);
    expect(items[0]).toEqual({
      label: "Mean annual loss, equal-weighted",
      value: "2.000%",
      note: "of asset value, over 2 hazards. Historical, same hazards: 2.000%",
    });
    expect(items[1]).toMatchObject({ value: "2 of 3", note: null });
    expect(items[3]).toMatchObject({ value: "50%", note: "1 asset had no building type to use" });
  });

  it("names physrisk's baseline instead of comparing it with itself", () => {
    const items = kpiItems(SUMMARY, TRAJECTORY[0], [], true);
    expect(items[0].note).toBe(
      "of asset value, over 2 hazards. physrisk's present-day baseline, which it treats as 2025",
    );
  });

  it("counts assets missing some results", () => {
    const items = kpiItems({ ...SUMMARY, failed_assets: 2 }, TRAJECTORY[4], [], false);
    expect(items[1].note).toBe("2 assets missing some results");
  });
});

describe("typeSourceCounts", () => {
  it("counts assessed assets only, by where their type came from", () => {
    const assets = [
      ...ASSETS,
      asset(4, { type_source: "subtype" }),
      asset(5, { type_source: "assumed", assessable: false }),
    ];
    expect(typeSourceCounts(assets)).toEqual({ class: 1, subtype: 1, assumed: 1 });
  });
});

describe("mapViewFeatures", () => {
  const assets = [
    asset(1, { lat: 40, lon: -4 }),
    asset(2, { lat: 30, lon: -95 }),
    asset(3, { lat: 41, lon: -3, assessable: false }),
  ] as Asset[];

  it("without clusters, colours every point by a hazard score and keeps no result hollow", () => {
    const rows = [
      row(1, 0.01, { scores: { Wind: { hazard: "Wind", score: 3, label: "High" } as never } }),
      row(2, 0.02, { scores: { Wind: { hazard: "Wind", score: -2, label: "No data" } as never } }),
    ];
    const { features, bounds } = mapViewFeatures(assets, [], rows, "Wind", false, "#fff");
    expect(props(features).map((p) => p.color)).toEqual([
      scoreColor(3, false),
      "rgba(0,0,0,0)",
      "rgba(0,0,0,0)",
    ]);
    expect(props(features).map((p) => p.ring)).toEqual(["#fff", NO_RESULT_COLOR, NO_RESULT_COLOR]);
    expect(props(features).every((p) => p.opacity === 1)).toBe(true);
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
        row_nums: [1, 3],
        lat: 40.5,
        lon: -3.5,
        bounds: [-4, 40, -3, 41],
      },
    ];
    const rows = [row(1, 0.01), row(2, 0.02)];
    const { features } = mapViewFeatures(assets, clusters, rows, COLOR_BY_TOTAL, false, "#fff");
    expect(features.features).toHaveLength(1);
    expect(props(features)[0]).toMatchObject({ clusterId: 7, opacity: BUBBLE_OPACITY });
  });
});

describe("mapLegend", () => {
  const base = { rows: [row(1, 0.01), row(2, 0.02)], hasClusters: false, outside: 0, dark: false };

  it("lists loss classes for total loss, and the hollow no-result mark", () => {
    const items = mapLegend({ ...base, colorBy: COLOR_BY_TOTAL, interactive: true });
    expect(items[0]).toEqual({
      kind: "heading",
      label: "Total annual loss, about a fifth of assets per colour:",
    });
    expect(items.filter((i) => i.kind === "dot")).toHaveLength(2);
    expect(items.at(-1)).toEqual({ kind: "hollow", label: "No result or excluded" });
  });

  it("lists the five score steps for a hazard", () => {
    const items = mapLegend({ ...base, colorBy: "Wind", interactive: true });
    expect(items.slice(0, 5)).toEqual(
      SCORE_LABELS.map((label, i) => ({ kind: "dot", color: ramp(false)[i], label })),
    );
  });

  it("drops the zoom and click hints from a still picture", () => {
    const options = { ...base, colorBy: COLOR_BY_TOTAL, hasClusters: true, outside: 2 };
    const live = mapLegend({ ...options, interactive: true }).slice(-2);
    const still = mapLegend({ ...options, interactive: false }).slice(-2);
    expect(live.map((i) => i.label)).toEqual([
      "Bubbles: groups of nearby assets, sized by count and coloured by their mean. Zoom in or click one to see each asset",
      "2 assets outside any group show when you zoom in",
    ]);
    expect(still.map((i) => i.label)).toEqual([
      "Bubbles: groups of nearby assets, sized by count and coloured by their mean",
      "2 assets outside any group aren't drawn at this scale",
    ]);
  });
});
