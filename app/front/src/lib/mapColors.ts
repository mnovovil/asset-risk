/** Map point colours: one hue from light to dark, stepped per theme, as MapLibre needs real hex. */

import { scoreKind } from "@/lib/dashboard";

const LIGHT_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"];
const DARK_RAMP = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"];
export const NO_RESULT_COLOR = "#898781";
const SCORE_STEPS = 5;

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
