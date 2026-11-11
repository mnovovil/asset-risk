/**
 * Map colours, from green (lowest) to red (highest), stepped per theme, as MapLibre needs real hex.
 *
 * A semantic heat scale, so several hues on purpose. Lightness only ever moves one way (light to
 * dark on the light surface, dark to light on the dark one), so the order still reads for red-green
 * colour-blind readers and in greyscale. Both ramps pass the dataviz validator's --ordinal checks
 * (lightness monotone, adjacent steps >= 0.06 apart, light end >= 2:1 on the surface) against the
 * --surface colours in styles.css; its "single hue" check fails by design. Re-run it before changing
 * them. A missing result is told apart by being hollow, not by its colour.
 */

import { scoreKind } from "@/lib/dashboard";

const LIGHT_RAMP = ["#68c85f", "#93a703", "#ad7c0e", "#af4e03", "#a50e15"];
const DARK_RAMP = ["#186a23", "#637505", "#a4780a", "#e66e0a", "#ff7f73"];
export const NO_RESULT_COLOR = "#898781";
const SCORE_STEPS = 5;

/** What each score step means, lowest first. */
export const SCORE_LABELS = ["Very low", "Low", "Medium", "High", "Very high"];

export const ramp = (dark: boolean) => (dark ? DARK_RAMP : LIGHT_RAMP);

export function scoreColor(score: number, dark: boolean): string | null {
  if (scoreKind(score) !== "scored") return null;
  return ramp(dark)[Math.min(score, SCORE_STEPS - 1)];
}

/** The q-quantile of sorted values, interpolating linearly between neighbours. */
function quantile(sorted: number[], q: number): number {
  const position = (sorted.length - 1) * q;
  const below = Math.floor(position);
  const above = Math.min(below + 1, sorted.length - 1);
  return sorted[below] + (sorted[above] - sorted[below]) * (position - below);
}

/**
 * Where each loss class ends: the quintiles of the assets' losses. Each colour then holds about a
 * fifth of the assets, so one extreme loss can't push the rest into the lowest class, as equal-width
 * classes from zero to the largest loss did.
 */
export function lossBreaks(totals: number[]): number[] {
  if (totals.length === 0) return [];
  const sorted = [...totals].sort((a, b) => a - b);
  return Array.from({ length: SCORE_STEPS - 1 }, (_, i) => quantile(sorted, (i + 1) / SCORE_STEPS));
}

/** The class a loss falls in. A loss equal to a break stays below it, so ties share a class. */
export const lossClass = (total: number, breaks: number[]) =>
  breaks.filter((limit) => total > limit).length;

export const totalColor = (total: number, breaks: number[], dark: boolean): string =>
  ramp(dark)[lossClass(total, breaks)];

export interface LossLegendItem {
  color: string;
  min: number;
  max: number;
  assets: number;
}

/** One legend entry per class that has assets, with the range of losses actually in it. */
export function lossLegend(totals: number[], breaks: number[], dark: boolean): LossLegendItem[] {
  const items = new Map<number, LossLegendItem>();
  for (const total of totals) {
    const step = lossClass(total, breaks);
    const item = items.get(step);
    if (item) {
      item.min = Math.min(item.min, total);
      item.max = Math.max(item.max, total);
      item.assets += 1;
    } else {
      items.set(step, { color: ramp(dark)[step], min: total, max: total, assets: 1 });
    }
  }
  return [...items.entries()].sort(([a], [b]) => a - b).map(([, item]) => item);
}
