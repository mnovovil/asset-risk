import { describe, expect, it } from "vitest";

import type { AssetTotal, Summary, TrajectoryPoint } from "@/api/client";
import {
  type AssetRow,
  barData,
  buildRows,
  kpiItems,
  trajectorySeries,
  valueCoverage,
  valueRows,
} from "@/lib/dashboard";
import { money } from "@/lib/format";
import { mapLegend } from "@/lib/mapLegend";
import { COLOR_BY_EXPECTED_LOSS, COLOR_BY_TOTAL, toFeatures } from "@/lib/mapFeatures";
import { reportContent } from "@/lib/report";

import { asset, SUMMARY, TRAJECTORY } from "./helpers";

const VALUED: Summary = {
  ...SUMMARY,
  has_values: true,
  valued_assets: 2,
  missing_values: 1,
  invalid_values: 0,
  total_value: 400,
  currency: "EUR",
};

const POINT: TrajectoryPoint = {
  ...TRAJECTORY[4],
  valued_assets: 2,
  valued_total: 400,
  weighted_mean_total_aal: 0.025,
  weighted_mean_shared_aal: 0.0075,
  expected_loss_total: 10,
  expected_loss_shared: 3,
};

const total = (
  row_num: number,
  total_aal: number | null,
  value: number | null,
  status = value === null ? "missing" : "given",
): AssetTotal => ({
  row_num,
  asset_id: `a${row_num}`,
  total_aal,
  shared_aal: total_aal,
  hazards: 1,
  value,
  value_status: status,
  expected_loss: value === null || total_aal === null ? null : total_aal * value,
  shared_expected_loss: null,
});

const impact = (row_num: number, hazard: string, aal: number) => ({
  row_num,
  asset_id: `a${row_num}`,
  lat: 0,
  lon: 0,
  hazard,
  impact_type: "damage",
  aal,
  aal_std: null,
});

describe("money", () => {
  it("formats an amount in the portfolio's currency", () => {
    expect(money(1500, "USD")).toContain("$");
    expect(money(1500, "EUR")).toContain("€");
    expect(money(1234, "JPY")).not.toMatch(/[.,]\d{2}$/);
  });

  it("never shows a unitless amount as money", () => {
    expect(money(1500, null)).toMatch(/value units$/);
    expect(money(1500, null)).not.toContain("$");
  });

  it("keeps a missing amount apart from zero", () => {
    expect(money(null, "USD")).toBe("–");
    expect(money(0, "USD")).not.toBe("–");
  });
});

describe("value rows", () => {
  const rows = buildRows(
    [total(1, 0.03, 100), total(2, 0.07, 300), total(3, 0.5, null), total(4, 0.9, null, "invalid")],
    [impact(1, "Wind", 0.01), impact(1, "Fire", 0.02), impact(2, "Wind", 0.07)],
    [],
    [impact(1, "Wind", 0.001), impact(2, "Wind", 0.002)],
  );

  it("carry each asset's value and expected loss, only when the value is usable", () => {
    expect(rows.map((r) => [r.value, r.expectedLoss])).toEqual([
      [100, 3],
      [300, expect.closeTo(21)],
      [null, null],
      [null, null],
    ]);
  });

  it("turn every loss into an amount and leave out assets without a value", () => {
    const scaled = valueRows(rows);
    expect(scaled.map((r) => r.rowNum)).toEqual([1, 2]);
    expect(scaled[0].total).toBeCloseTo(3);
    expect(scaled[0].aal.Fire).toBeCloseTo(2);
    expect(scaled[1].historical).toBeCloseTo(0.6);
  });

  it("rank the bars by expected loss, so a large share of a small asset ranks lower", () => {
    expect(barData(valueRows(rows)).map((d) => d.rowNum)).toEqual([2, 1]);
    expect(barData(rows).map((d) => d.rowNum)).toEqual([4, 3, 2, 1]);
  });
});

describe("kpiItems by value", () => {
  const row = (rowNum: number, historical: number, value: number | null): AssetRow => ({
    rowNum,
    label: `a${rowNum}`,
    total: 0.01,
    historical,
    aal: {},
    scores: {},
    value,
    expectedLoss: value === null ? null : 0.01 * value,
  });

  it("shows the value-weighted mean and expected loss with their coverage", () => {
    const rows = [row(1, 0.01, 100), row(2, 0.03, 300), row(3, 0.5, null)];
    const items = kpiItems(VALUED, POINT, rows, false, "value");
    expect(items.map((i) => i.label)).toEqual([
      "Mean annual loss, value-weighted",
      "Expected annual loss",
      "Assets assessed",
      "Assets excluded",
      "Building type assumed",
    ]);
    expect(items[0].value).toBe("2.500%");
    // Historical over the same hazards, weighted the same way: (1 + 9) / 400.
    expect(items[0].note).toBe(
      "of asset value, over 2 hazards. Historical, same hazards: 2.500%",
    );
    expect(items[1].value).toContain("€");
    expect(items[1].note).toMatch(/^From 2 of 3 assets, worth .*\. 1 asset has no usable value\.$/);
  });

  it("stays equal-weighted by default", () => {
    expect(kpiItems(VALUED, POINT, [], false)[0].label).toBe("Mean annual loss, equal-weighted");
  });

  it("says how many values were invalid", () => {
    const note = valueCoverage({ ...VALUED, missing_values: 1, invalid_values: 2 }, POINT);
    expect(note).toMatch(/3 assets have no usable value \(2 invalid\)\.$/);
  });
});

describe("trajectorySeries by value", () => {
  it("uses the value-weighted shared-hazard means", () => {
    const trajectory = [{ ...TRAJECTORY[0], weighted_mean_shared_aal: 0.001 }, POINT];
    const { data } = trajectorySeries(trajectory, "value");
    expect(data).toEqual([{ year: 2050, historical: 0.001, ssp585: 0.0075 }]);
  });

  it("draws nothing for a run without weighted figures", () => {
    expect(trajectorySeries(TRAJECTORY, "value").data).toEqual([]);
  });
});

describe("the map by expected loss", () => {
  const row = (rowNum: number, value: number | null, expectedLoss: number | null): AssetRow => ({
    rowNum,
    label: `a${rowNum}`,
    total: 0.01,
    historical: null,
    aal: {},
    scores: {},
    value,
    expectedLoss,
  });
  const rows = [row(1, 100, 1), row(2, 1000, 10), row(3, null, null)];
  const assets = [asset(1), asset(2), asset(3)];

  it("colours assets with a value and leaves the rest hollow, never low", () => {
    const features = toFeatures(assets, rows, COLOR_BY_EXPECTED_LOSS, null, false, "#fff", false, "EUR");
    const props = features.features.map((f) => f.properties as Record<string, unknown>);
    expect(props[0].color).not.toBe(props[1].color);
    expect(props[2].color).toBe("rgba(0,0,0,0)");
    expect(props[2].detail).toBe("No usable value");
    expect(props[1].detail).toMatch(/^Expected annual loss .*€/);
  });

  it("labels the legend in money", () => {
    const legend = mapLegend({
      rows,
      colorBy: COLOR_BY_EXPECTED_LOSS,
      hasClusters: false,
      outside: 0,
      dark: false,
      interactive: true,
      currency: "EUR",
    });
    expect(legend[0]).toEqual({
      kind: "heading",
      label: "Expected annual loss, about a fifth of assets per colour:",
    });
    expect(legend.some((item) => item.kind === "dot" && item.label.includes("€"))).toBe(true);
    expect(legend.at(-1)).toEqual({ kind: "hollow", label: "No result, no usable value, or excluded" });
  });
});

describe("the report by value", () => {
  const run = {
    summary: VALUED,
    assets: [asset(1), asset(2), asset(3)],
    clusters: [],
    trajectory: [POINT],
    coverage: [],
    historical: [],
  };
  const base = {
    label: "offices.csv",
    createdAt: "2026-10-30T23:30:00Z",
    generatedAt: new Date("2026-11-18T09:00:00Z"),
    pair: { scenario: "ssp585", year: 2050 },
    colorBy: COLOR_BY_TOTAL,
    run,
    rows: [],
    defaultType: null,
  };

  it("names the weighting and its coverage", () => {
    const content = reportContent({ ...base, weighting: "value", colorBy: COLOR_BY_EXPECTED_LOSS });
    expect(content.facts.slice(3)).toEqual([
      { label: "Map coloured by", value: "Expected annual loss" },
      { label: "Weighting", value: "By value, in EUR" },
      { label: "Value coverage", value: expect.stringMatching(/^From 2 of 3 assets/) },
    ]);
    expect(content.kpis[0].label).toBe("Mean annual loss, value-weighted");
  });

  it("says it's equal-weighted when the run has values but the view doesn't use them", () => {
    const content = reportContent(base);
    expect(content.facts.at(-1)).toEqual({
      label: "Weighting",
      value: "Equal: every asset counts the same",
    });
  });

  it("never weights a run without values", () => {
    const content = reportContent({
      ...base,
      weighting: "value",
      run: { ...run, summary: SUMMARY },
    });
    expect(content.facts.map((f) => f.label)).not.toContain("Weighting");
    expect(content.kpis[0].label).toBe("Mean annual loss, equal-weighted");
  });
});
