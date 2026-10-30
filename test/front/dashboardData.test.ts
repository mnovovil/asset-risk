import { describe, expect, it } from "vitest";

import {
  barData,
  buildRows,
  defaultPair,
  hazardColumns,
  missingHazards,
  scoreKind,
  TOP_ASSETS,
  trajectorySeries,
} from "@/lib/dashboard";
import { joinList, percent, percentTick, truncate } from "@/lib/format";
import { hazardColor, sortHazards } from "@/lib/hazards";
import { scoreColor, totalColor } from "@/lib/mapColors";

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

  it("keep the largest loss in the top class", () => {
    expect(totalColor(0.02, 0.02, false)).toBe(scoreColor(4, false));
    expect(totalColor(0, 0.02, false)).toBe(scoreColor(0, false));
    expect(totalColor(0, 0, false)).toBe(scoreColor(0, false));
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
