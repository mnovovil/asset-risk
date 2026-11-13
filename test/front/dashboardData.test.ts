import { describe, expect, it } from "vitest";

import {
  assetChartOptions,
  assetSeries,
  barData,
  buildRows,
  BASELINE,
  defaultPair,
  hasBaseline,
  isBaseline,
  lossHazards,
  pairLabel,
  preferredYear,
  hazardColumns,
  missingHazards,
  scoreKind,
  TOP_ASSETS,
  trajectorySeries,
  yearsOf,
} from "@/lib/dashboard";
import { joinList, percent, percentTick, truncate } from "@/lib/format";
import { hazardColor, sortHazards } from "@/lib/hazards";
import { lossBreaks, lossClass, lossLegend, ramp, scoreColor, totalColor } from "@/lib/mapColors";

import { COVERAGE, TRAJECTORY } from "./helpers";

const total = (row_num: number, total_aal: number | null) => ({
  row_num,
  asset_id: `a${row_num}`,
  total_aal,
  shared_aal: total_aal,
  hazards: 1,
});
const impact = (row_num: number, hazard: string, aal: number | null) => ({
  row_num,
  asset_id: `a${row_num}`,
  lat: 1,
  lon: 2,
  hazard,
  impact_type: "damage",
  aal,
  aal_std: null,
});
const score = (row_num: number, hazard: string, value: number) => ({
  row_num,
  asset_id: `a${row_num}`,
  hazard,
  score: value,
  label: "x",
});

describe("percent", () => {
  it("keeps zero distinct from a very small loss", () => {
    expect(percent(0)).toBe("0%");
    expect(percent(0.0000001)).toBe("<0.001%");
    expect(percent(0.00125)).toBe("0.125%");
  });

  it("shows no result differently from zero", () => {
    expect(percent(null)).toBe("–");
    expect(percent(undefined)).toBe("–");
  });

  it("formats axis ticks", () => {
    expect(percentTick(0)).toBe("0%");
    expect(percentTick(0.0025)).toBe("0.25%");
  });
});

describe("scoreKind", () => {
  it.each([
    [0, "scored"],
    [4, "scored"],
    [-1, "no_model"],
    [-2, "no_data"],
    [-3, "error"],
  ])("reads %i as %s", (value, kind) => {
    expect(scoreKind(value)).toBe(kind);
  });
});

describe("buildRows", () => {
  it("compares history over only the hazards this scenario has", () => {
    const rows = buildRows(
      [total(1, 0.01)],
      [impact(1, "Wind", 0.01)],
      [],
      [impact(1, "Wind", 0.002), impact(1, "Fire", 0.5)],
    );
    expect(rows[0].historical).toBeCloseTo(0.002);
  });

  it("has no historical figure when there's nothing to compare", () => {
    const rows = buildRows([total(1, 0.01)], [impact(1, "Wind", 0.01)], [], []);
    expect(rows[0].historical).toBeNull();
  });

  it("names an asset with no id by its row", () => {
    const rows = buildRows([{ ...total(7, 0), asset_id: null }], [], [], []);
    expect(rows[0].label).toBe("Row 7");
  });

  it("adds up a hazard with more than one impact type", () => {
    const rows = buildRows(
      [total(1, 0.3)],
      [impact(1, "Wind", 0.1), impact(1, "Wind", 0.2)],
      [],
      [],
    );
    expect(rows[0].aal.Wind).toBeCloseTo(0.3);
  });
});

describe("hazardColumns", () => {
  it("sets apart hazards with no result for any asset", () => {
    const rows = buildRows(
      [total(1, 0), total(2, 0)],
      [],
      [
        score(1, "Wind", 1),
        score(2, "Wind", -2),
        score(1, "ChronicHeat", -1),
        score(2, "ChronicHeat", -1),
        score(1, "PluvialInundation", -2),
        score(2, "PluvialInundation", -2),
      ],
      [],
    );
    expect(hazardColumns(rows)).toEqual({
      scored: ["Wind"],
      noModel: ["ChronicHeat"],
      noData: ["PluvialInundation"],
    });
  });
});

describe("barData", () => {
  it("draws only the highest losses, largest first", () => {
    const rows = buildRows(
      Array.from({ length: 40 }, (_, i) => total(i + 1, i)),
      [],
      [],
      [],
    );
    const data = barData(rows);
    expect(data).toHaveLength(TOP_ASSETS);
    expect(data[0].total).toBe(39);
  });

  it("places the total's label past a marker that reaches further than the bar", () => {
    const rows = buildRows(
      [total(1, 0.1)],
      [impact(1, "Wind", 0.1)],
      [],
      [impact(1, "Wind", 0.4)],
    );
    expect(barData(rows)[0].labelEnd).toBeCloseTo(0.4);
  });

  it("rounds the last segment that actually has a value", () => {
    const rows = buildRows(
      [total(1, 0.3)],
      [impact(1, "RiverineInundation", 0.3), impact(1, "Hail", 0)],
      [],
      [],
    );
    expect(barData(rows)[0].lastHazard).toBe("RiverineInundation");
  });
});

describe("the selected scenario", () => {
  it("starts on the scenario with the most hazards, near 2050", () => {
    expect(defaultPair(TRAJECTORY)).toEqual({ scenario: "ssp585", year: 2050 });
  });

  it("leaves out years with no results, as 2025 had", () => {
    const empty2025 = { ...TRAJECTORY[3], year: 2025, assets: 0, mean_total_aal: null, mean_shared_aal: null };
    const trajectory = [...TRAJECTORY, empty2025];
    expect(yearsOf(trajectory, "ssp585")).toEqual([2030, 2050]);
    expect(defaultPair(trajectory)).toEqual({ scenario: "ssp585", year: 2050 });
  });

  it("keeps every year of a scenario with no results anywhere", () => {
    expect(yearsOf(TRAJECTORY, "ssp370")).toEqual([2050]);
  });

  it("never starts on the baseline", () => {
    expect(isBaseline(defaultPair(TRAJECTORY))).toBe(false);
  });

  it("knows the baseline, and only offers it when it has results", () => {
    expect(isBaseline(BASELINE)).toBe(true);
    expect(isBaseline({ scenario: "ssp585", year: 2050 })).toBe(false);
    expect(hasBaseline(TRAJECTORY)).toBe(true);
    const empty = TRAJECTORY.map((p) => (p.year === null ? { ...p, assets: 0 } : p));
    expect(hasBaseline(empty)).toBe(false);
  });

  it("names the selected pair", () => {
    expect(pairLabel(BASELINE)).toBe("Today (baseline)");
    expect(pairLabel({ scenario: "ssp585", year: 2050 })).toBe("SSP5-8.5, 2050");
  });

  it("prefers the year nearest 2050", () => {
    expect(preferredYear([2030, 2045, 2080])).toBe(2045);
    expect(preferredYear([])).toBeUndefined();
  });

  it("takes the baseline's columns from its losses, as it has no scores", () => {
    const rows = buildRows(
      [{ row_num: 1, asset_id: "a", total_aal: 0.01, shared_aal: 0.01, hazards: 2 }],
      [
        { row_num: 1, asset_id: "a", lat: 0, lon: 0, hazard: "Wind", impact_type: "damage", aal: 0.004, aal_std: null },
        { row_num: 1, asset_id: "a", lat: 0, lon: 0, hazard: "Fire", impact_type: "damage", aal: 0.006, aal_std: null },
      ],
      [],
      [],
    );
    expect(lossHazards(rows)).toEqual(sortHazards(["Wind", "Fire"]));
  });

  it("copes with no scenarios", () => {
    expect(defaultPair([])).toBeNull();
  });

  it("finds hazards missing from a scenario", () => {
    expect(missingHazards(COVERAGE, { scenario: "ssp245", year: 2050 })).toEqual(["Fire"]);
    expect(missingHazards(COVERAGE, { scenario: "ssp585", year: 2050 })).toEqual([]);
  });
});

describe("trajectorySeries", () => {
  it("uses shared-hazard means, leaving out scenarios with no results", () => {
    const { scenarios, data } = trajectorySeries(TRAJECTORY);
    expect(scenarios).toEqual(["ssp245", "ssp585"]);
    expect(data).toEqual([
      { year: 2030, historical: 0.002, ssp245: null, ssp585: 0.004 },
      { year: 2050, historical: 0.002, ssp245: 0.006, ssp585: 0.005 },
    ]);
  });
});

describe("colours", () => {
  it("follow the hazard, not its position", () => {
    expect(hazardColor("Wind")).toBe("var(--series-3)");
    expect(sortHazards(["Hail", "Wind", "RiverineInundation"])).toEqual([
      "RiverineInundation",
      "Wind",
      "Hail",
    ]);
  });

  it("give no colour to a score with no result", () => {
    expect(scoreColor(-1, false)).toBeNull();
    expect(scoreColor(-2, true)).toBeNull();
    expect(scoreColor(0, false)).not.toBeNull();
  });

  it("step differently in each theme", () => {
    expect(scoreColor(4, false)).not.toBe(scoreColor(4, true));
  });

  it("keep the largest loss in the top class and the smallest in the bottom one", () => {
    const breaks = lossBreaks([0, 0.005, 0.01, 0.015, 0.02]);
    expect(totalColor(0.02, breaks, false)).toBe(scoreColor(4, false));
    expect(totalColor(0, breaks, false)).toBe(scoreColor(0, false));
    expect(totalColor(0, lossBreaks([0, 0]), false)).toBe(scoreColor(0, false));
  });

  it("put about a fifth of assets in each class, however extreme the largest loss", () => {
    // 99 losses from 0.01% to 0.99%, and one outlier at 50%. Equal-width classes from zero to the
    // largest would put all 99 in the lowest class.
    const totals = [...Array.from({ length: 99 }, (_, i) => (i + 1) / 10000), 0.5];
    const breaks = lossBreaks(totals);
    const counts = [0, 0, 0, 0, 0];
    for (const total of totals) counts[lossClass(total, breaks)] += 1;
    expect(counts).toEqual([20, 20, 20, 20, 20]);
    expect(lossClass(0.5, breaks)).toBe(4);
  });

  it("let tied losses share a class, and leave empty classes out of the legend", () => {
    const totals = [0, 0, 0, 0, 0, 0, 0.01, 0.02, 0.03, 0.04];
    const legend = lossLegend(totals, lossBreaks(totals), false);
    expect(legend[0]).toEqual({ color: ramp(false)[0], min: 0, max: 0, assets: 6 });
    expect(legend.reduce((sum, item) => sum + item.assets, 0)).toBe(10);
    expect(legend.at(-1)?.max).toBe(0.04);
  });

  it("have no breaks without losses", () => {
    expect(lossBreaks([])).toEqual([]);
    expect(totalColor(0.01, [], false)).toBe(ramp(false)[0]);
  });
});

describe("text helpers", () => {
  it("shorten long labels", () => {
    expect(truncate("abcdefgh", 5)).toBe("abcd…");
    expect(truncate("abc", 5)).toBe("abc");
  });

  it("join lists", () => {
    expect(joinList(["a"])).toBe("a");
    expect(joinList(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("an asset's charts over time", () => {
  const impact = (scenario: string, year: number | null, hazard: string, aal: number | null, type = "damage") => ({
    scenario,
    year,
    hazard,
    impact_type: type,
    aal,
    aal_std: null,
    hazard_paths: [],
  });
  const score = (scenario: string, year: number, hazard: string, value: number) => ({
    scenario,
    year,
    hazard,
    score: value,
    label: null,
  });
  const asset = {
    impacts: [
      impact("historical", null, "Wind", 0.001),
      impact("ssp585", 2050, "Wind", 0.004),
      impact("ssp585", 2030, "Wind", 0.002),
      impact("ssp245", 2050, "Wind", null),
      impact("ssp245", 2030, "Wind", 0.0015),
      impact("ssp585", 2050, "RiverineInundation", 0.01),
      impact("ssp585", 2050, "RiverineInundation", 0.005, "disruption"),
    ],
    scores: [
      score("ssp585", 2050, "Wind", 3),
      score("ssp585", 2030, "Wind", 9),
      score("ssp245", 2050, "Wind", -2),
      score("ssp245", 2030, "Wind", -1),
      score("ssp585", 2050, "Fire", 0),
    ],
  };
  const RUN_SCENARIOS = ["ssp245", "ssp370", "ssp585"];

  it("offers losses then scores, each in hazard order", () => {
    expect(assetChartOptions(asset).map((o) => o.label)).toEqual([
      "Annual loss — River flood",
      "Annual loss — Tropical cyclone wind",
      "Score — Tropical cyclone wind",
      "Score — Wildfire",
    ]);
    expect(assetChartOptions(asset)[0]).toMatchObject({ key: "loss:RiverineInundation", metric: "loss" });
  });

  it("draws the baseline flat, apart from the scenario lines, with years in order", () => {
    const series = assetSeries(asset, "loss", "Wind", RUN_SCENARIOS);
    expect(series.baseline).toBe(0.001);
    expect(series.scenarios).toEqual(["ssp245", "ssp585"]);
    expect(series.data).toEqual([
      { year: 2030, historical: 0.001, ssp245: 0.0015, ssp585: 0.002 },
      { year: 2050, historical: 0.001, ssp245: null, ssp585: 0.004 },
    ]);
  });

  it("keeps a missing loss null, never zero", () => {
    const series = assetSeries(asset, "loss", "Wind", RUN_SCENARIOS);
    expect(series.data[1].ssp245).toBeNull();
  });

  it("adds up impact types", () => {
    const series = assetSeries(asset, "loss", "RiverineInundation", RUN_SCENARIOS);
    expect(series.data).toEqual([{ year: 2050, historical: null, ssp585: 0.015 }]);
  });

  it("names the scenarios with nothing for the hazard", () => {
    expect(assetSeries(asset, "loss", "Wind", RUN_SCENARIOS).missingScenarios).toEqual(["ssp370"]);
    expect(assetSeries(asset, "loss", "RiverineInundation", RUN_SCENARIOS).missingScenarios).toEqual([
      "ssp245",
      "ssp370",
    ]);
  });

  it("gives scores no baseline, and turns negative scores into notes", () => {
    const series = assetSeries(asset, "score", "Wind", RUN_SCENARIOS);
    expect(series.baseline).toBeNull();
    expect(series.scenarios).toEqual(["ssp585"]);
    // A score past the top step is drawn at the top, as on the map.
    expect(series.data).toEqual([
      { year: 2030, historical: null, ssp585: 4 },
      { year: 2050, historical: null, ssp585: 3 },
    ]);
    expect(series.notes).toEqual([
      { scenario: "ssp245", year: 2030, kind: "no_model" },
      { scenario: "ssp245", year: 2050, kind: "no_data" },
    ]);
    // ssp245 is explained by its notes, so only ssp370 is missing.
    expect(series.missingScenarios).toEqual(["ssp370"]);
  });

  it("draws a score of zero, which is Very low, not missing", () => {
    const series = assetSeries(asset, "score", "Fire", RUN_SCENARIOS);
    expect(series.data).toEqual([{ year: 2050, historical: null, ssp585: 0 }]);
  });
});
