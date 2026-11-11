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

/** Equal-width classes from zero to the portfolio's largest loss. */
export function totalColor(total: number, max: number, dark: boolean): string {
  if (max <= 0) return ramp(dark)[0];
  const step = Math.min(Math.floor((total / max) * SCORE_STEPS), SCORE_STEPS - 1);
  return ramp(dark)[step];
}
