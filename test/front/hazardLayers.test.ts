import { describe, expect, it } from "vitest";

import type { HazardMapLayer } from "@/api/client";
import { formatValue } from "@/lib/format";
import { layerGroups, pickLayer } from "@/lib/hazardLayers";

import { hazardGrids } from "./helpers";

const flood = (hazard: string, available = true): HazardMapLayer => ({
  hazard,
  available,
  reason: available ? null : "physrisk has no flood map for this scenario",
  return_period: 1000,
  units: "m",
  min_value: 0,
  max_value: 2,
  max_zoom: 6,
  legend: [],
  tile_url: available ? "/tiles/{z}/{x}/{y}.png" : null,
});

const grids = (scenario = "ssp585") =>
  hazardGrids(`/api/runs/r/assets/1/hazard-grids?scenario=${scenario}&year=2050`);

describe("layerGroups", () => {
  it("groups flood maps and grids by hazard, in the hazards' fixed order", () => {
    const groups = layerGroups([flood("CoastalInundation"), flood("RiverineInundation")], grids());
    expect(groups.map((g) => [g.label, g.options.map((o) => o.id)])).toEqual([
      ["River flood", ["RiverineInundation"]],
      ["Coastal flood", ["CoastalInundation"]],
      ["Tropical cyclone wind", ["wind_iris_max_speed"]],
      ["Chronic heat", ["heat_jupiter_days_above_35c"]],
      ["Land subsidence", ["subsidence_csm_rate"]],
    ]);
  });

  it("marks only the layers that feed the damage figures", () => {
    const labels = layerGroups([], grids()).flatMap((g) => g.options.map((o) => o.label));
    expect(labels.filter((label) => label.includes("used in damage figures"))).toEqual([
      "Tropical cyclone wind speed · 1 in 100 years · used in damage figures",
    ]);
  });

  it("labels a layer with no data for the pair, and keeps it selectable", () => {
    const groups = layerGroups([flood("RiverineInundation", false)], grids("historical"));
    const heat = groups.find((g) => g.hazard === "ChronicHeat")!.options[0];
    expect(heat.label).toBe("Hot days · Above 35°C · No data for this scenario/year");
    expect(groups[0].options[0].label).toContain("No data for this scenario/year");
    expect(pickLayer(groups, heat.id)?.id).toBe(heat.id);
  });

  it("lists a hazard with results but no map of either kind, disabled", () => {
    const groups = layerGroups([], [], ["PluvialInundation"]);
    expect(groups).toEqual([
      {
        hazard: "PluvialInundation",
        label: "Surface water flood",
        options: [
          {
            kind: "none",
            id: "none:PluvialInundation",
            hazard: "PluvialInundation",
            label: "No public map",
          },
        ],
      },
    ]);
    expect(pickLayer(groups, "none:PluvialInundation")).toBeNull();
  });

  it("keeps flood and grid ids apart", () => {
    const options = layerGroups([flood("RiverineInundation")], grids()).flatMap((g) => g.options);
    const ids = options.map((o) => o.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const option of options) {
      expect(/^[a-z0-9_]+$/.test(option.id)).toBe(option.kind === "grid");
    }
  });
});

describe("pickLayer", () => {
  it("falls back to the first flood map with data, then to any layer", () => {
    const groups = layerGroups(
      [flood("RiverineInundation", false), flood("CoastalInundation")],
      grids(),
    );
    expect(pickLayer(groups, "gone")?.id).toBe("CoastalInundation");
    expect(pickLayer(layerGroups([], grids()), null)?.id).toBe("wind_iris_max_speed");
    expect(pickLayer([], null)).toBeNull();
  });
});

describe("formatValue", () => {
  it("keeps three significant figures at any scale", () => {
    expect([0.030923, 24.365, 1214.9, 0].map(formatValue)).toEqual([
      "0.0309",
      "24.4",
      "1,210",
      "0",
    ]);
  });
});
