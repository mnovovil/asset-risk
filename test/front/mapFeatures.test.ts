import { describe, expect, it } from "vitest";

import type { Asset } from "@/api/client";
import type { AssetRow } from "@/lib/dashboard";
import { NO_RESULT_COLOR, ramp, scoreColor } from "@/lib/mapColors";
import { COLOR_BY_TOTAL, placeable, toFeatures } from "@/lib/mapFeatures";

import { asset } from "./helpers";

const ASSETS = [
  asset(1),
  asset(2),
  asset(3, { lat: null, lon: null, assessable: false, exclusion_reason: "invalid" }),
  asset(4),
] as Asset[];

const row = (rowNum: number, total: number | null): AssetRow => ({
  rowNum,
  label: `a${rowNum}`,
  total,
  historical: null,
  aal: {},
  scores: {},
});

const ROWS = [row(1, 0.01), row(2, 0.02), row(4, null)];

const props = (collection: GeoJSON.FeatureCollection) =>
  collection.features.map((f) => f.properties as Record<string, unknown>);

describe("toFeatures", () => {
  it("leaves out assets with no coordinates", () => {
    expect(placeable(ASSETS).map((a) => a.row_num)).toEqual([1, 2, 4]);
    const features = toFeatures(ASSETS, ROWS, COLOR_BY_TOTAL, null, false, "#fff", false);
    expect(props(features).map((p) => p.rowNum)).toEqual([1, 2, 4]);
  });

  it("with clusters, shows every asset only once zoomed in, except the selected one", () => {
    const features = toFeatures(ASSETS, ROWS, COLOR_BY_TOTAL, 2, false, "#fff", true);
    expect(props(features).map((p) => [p.rowNum, p.zoomedIn])).toEqual([
      [1, true],
      [2, false],
      [4, true],
    ]);
  });

  it("with no clusters, shows every asset at every zoom", () => {
    const features = toFeatures(ASSETS, ROWS, COLOR_BY_TOTAL, null, false, "#fff", false);
    expect(props(features).every((p) => p.zoomedIn === false)).toBe(true);
  });

  it("colours from green to red, and draws a missing result hollow", () => {
    const [low, high, none] = props(
      toFeatures(ASSETS, ROWS, COLOR_BY_TOTAL, null, false, "#fff", false),
    );
    expect(high.color).toBe(ramp(false).at(-1));
    expect(low.color).not.toBe(high.color);
    expect(none.color).toBe("rgba(0,0,0,0)");
    expect(none.ring).toBe(NO_RESULT_COLOR);
    expect(high.ring).toBe("#fff");
  });
});

/** OKLab lightness, as the dataviz validator measures it. */
function lightness(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return 0.2104542553 * l + 0.793617813 * m - 0.0040720468 * s;
}

/** Red minus green: negative at the green end, positive at the red end. */
const warmth = (hex: string) => parseInt(hex.slice(1, 3), 16) - parseInt(hex.slice(3, 5), 16);

describe("map ramp", () => {
  it.each([false, true])("runs from green to red (dark: %s)", (dark) => {
    const colors = ramp(dark);
    expect(colors).toHaveLength(5);
    expect(warmth(colors[0])).toBeLessThan(0);
    expect(warmth(colors[4])).toBeGreaterThan(0);
    expect(scoreColor(0, dark)).toBe(colors[0]);
    expect(scoreColor(4, dark)).toBe(colors[4]);
  });

  it("only ever gets darker on the light surface, so it reads without hue", () => {
    const steps = ramp(false).map(lightness);
    steps.slice(1).forEach((value, i) => expect(steps[i] - value).toBeGreaterThanOrEqual(0.06));
  });

  it("only ever gets lighter on the dark surface", () => {
    const steps = ramp(true).map(lightness);
    steps.slice(1).forEach((value, i) => expect(value - steps[i]).toBeGreaterThanOrEqual(0.06));
  });
});
