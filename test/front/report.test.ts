import { describe, expect, it } from "vitest";

import type { RunData } from "@/hooks/useDashboard";
import { type AssetRow, BASELINE } from "@/lib/dashboard";
import { COLOR_BY_TOTAL } from "@/lib/mapFeatures";
import { pageFormat, reportContent, reportFileName, slugify } from "@/lib/report";
import { REPORT_NOTES } from "@/lib/reportText";

import { ASSETS, COVERAGE, SUMMARY, TRAJECTORY } from "./helpers";

const RUN = {
  summary: SUMMARY,
  assets: ASSETS,
  clusters: [],
  trajectory: TRAJECTORY,
  coverage: COVERAGE,
  historical: [],
} as unknown as RunData;

const row = (rowNum: number, total: number | null): AssetRow => ({
  rowNum,
  label: `asset-${rowNum}`,
  total,
  historical: total,
  aal: { Wind: total },
  scores: {},
});

const input = (overrides = {}) => ({
  label: "Madrid offices.csv",
  createdAt: "2026-10-30T23:30:00Z",
  generatedAt: new Date("2026-11-18T09:00:00Z"),
  pair: { scenario: "ssp585", year: 2050 },
  colorBy: COLOR_BY_TOTAL,
  run: RUN,
  rows: [row(1, 0.01), row(2, 0.03)],
  defaultType: "Buildings/Commercial",
  ...overrides,
});

describe("reportContent", () => {
  it("describes the scenario, run and colouring the dashboard shows", () => {
    const content = reportContent(input());
    expect(content.title).toBe("Madrid offices.csv");
    expect(content.facts).toEqual([
      { label: "Scenario", value: "SSP5-8.5, 2050" },
      { label: "Run date", value: "2026-10-30" },
      { label: "Assets", value: "3" },
      { label: "Map coloured by", value: "Total annual loss" },
    ]);
    expect(content.kpis[0].value).toBe("2.000%");
    expect(content.noResults).toBeNull();
    expect(content.notes).toBe(REPORT_NOTES);
    expect(content.footer).toBe(
      "Madrid offices.csv · SSP5-8.5, 2050 · generated 2026-11-18 by asset-risk",
    );
  });

  it("keeps where building types came from visible, naming the assumed type", () => {
    expect(reportContent(input()).typeSource).toBe(
      "Building type of assessed assets, from Overture's class: 1, from its subtype: 0, assumed as Buildings/Commercial: 1.",
    );
    expect(reportContent(input({ defaultType: null })).typeSource).toContain("assumed: 1.");
  });

  it("for the baseline, names it and doesn't compare it with history", () => {
    const content = reportContent(input({ pair: BASELINE }));
    expect(content.facts[0].value).toBe("Today (baseline)");
    expect(content.kpis[0].note).toContain("physrisk's present-day baseline");
  });

  it("says why there are no charts when a scenario has no results", () => {
    expect(reportContent(input({ rows: [] })).noResults).toBe("This scenario has no results.");
    const none = { ...RUN, summary: { ...SUMMARY, assessable: 0 } } as RunData;
    expect(reportContent(input({ rows: [], run: none })).noResults).toBe(
      "No asset in this portfolio could be assessed.",
    );
  });

  it("legends a hazard's scores without the live map's zoom hints", () => {
    const content = reportContent(input({ colorBy: "Wind" }));
    expect(content.facts[3].value).toBe("Tropical cyclone wind score");
    expect(content.map.legend.map((i) => i.label)).toEqual([
      "Very low",
      "Low",
      "Medium",
      "High",
      "Very high",
      "No result or excluded",
    ]);
  });

  it("falls back to a generic title when the run has no label", () => {
    expect(reportContent(input({ label: "  " })).title).toBe("Portfolio run");
  });
});

describe("reportFileName", () => {
  const pair = { scenario: "ssp585", year: 2050 };

  it.each([
    ["Madrid offices.csv", "asset-risk_madrid-offices_ssp585_2050.pdf"],
    ["Café São Paulo.csv", "asset-risk_cafe-sao-paulo_ssp585_2050.pdf"],
    ['../../etc/"passwd"\u0000', "asset-risk_etc-passwd_ssp585_2050.pdf"],
    ["🏢🏭", "asset-risk_portfolio_ssp585_2050.pdf"],
    ["مكاتب", "asset-risk_portfolio_ssp585_2050.pdf"],
    ["", "asset-risk_portfolio_ssp585_2050.pdf"],
  ])("makes %j safe", (label, expected) => {
    expect(reportFileName(label, pair)).toBe(expected);
  });

  it("handles no label, and the baseline", () => {
    expect(reportFileName(null, BASELINE)).toBe("asset-risk_portfolio_baseline.pdf");
  });

  it("caps a long label without a trailing hyphen", () => {
    const slug = slugify(`${"a".repeat(59)} b`);
    expect(slug).toBe("a".repeat(59));
    expect(slugify("x".repeat(200))).toHaveLength(60);
  });
});

describe("pageFormat", () => {
  it.each([
    ["en-US", "letter"],
    ["en-CA", "letter"],
    ["es-MX", "letter"],
    ["en-GB", "a4"],
    ["es-ES", "a4"],
    ["de", "a4"],
    [undefined, "a4"],
    ["not a locale", "a4"],
  ])("%s → %s", (locale, format) => {
    expect(pageFormat(locale)).toBe(format);
  });
});
