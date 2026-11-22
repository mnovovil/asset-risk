/** What the risk map's legend says, shared by the dashboard map and the PDF report. */

import type { AssetRow } from "@/lib/dashboard";
import { count } from "@/lib/format";
import { lossBreaks, lossLegend, ramp, SCORE_LABELS } from "@/lib/mapColors";
import {
  COLOR_BY_EXPECTED_LOSS,
  formatLoss,
  isLossColoring,
  totalsOf,
} from "@/lib/mapFeatures";

export type LegendItem =
  | { kind: "heading"; label: string }
  | { kind: "dot"; color: string; label: string }
  | { kind: "hollow"; label: string }
  | { kind: "bubble"; label: string }
  | { kind: "text"; label: string };

interface LegendOptions {
  rows: AssetRow[];
  colorBy: string;
  hasClusters: boolean;
  /** Placeable assets in no cluster: not drawn in the opening view. */
  outside: number;
  dark: boolean;
  /** The live map can be zoomed and clicked; a picture of it can't. */
  interactive: boolean;
  /** The portfolio's currency, for expected loss. */
  currency?: string | null;
}

export function mapLegend({
  rows,
  colorBy,
  hasClusters,
  outside,
  dark,
  interactive,
  currency = null,
}: LegendOptions): LegendItem[] {
  const items: LegendItem[] = [];
  const expected = colorBy === COLOR_BY_EXPECTED_LOSS;
  if (isLossColoring(colorBy)) {
    const totals = totalsOf(rows, colorBy);
    const format = (loss: number) => formatLoss(loss, colorBy, currency);
    items.push({
      kind: "heading",
      label: `${expected ? "Expected" : "Total"} annual loss, about a fifth of assets per colour:`,
    });
    for (const item of lossLegend(totals, lossBreaks(totals), dark)) {
      items.push({
        kind: "dot",
        color: item.color,
        label: item.min === item.max ? format(item.min) : `${format(item.min)} to ${format(item.max)}`,
      });
    }
  } else {
    const colors = ramp(dark);
    SCORE_LABELS.forEach((label, index) => items.push({ kind: "dot", color: colors[index], label }));
  }
  items.push({
    kind: "hollow",
    label: expected ? "No result, no usable value, or excluded" : "No result or excluded",
  });
  if (hasClusters) {
    const bubble = "Bubbles: groups of nearby assets, sized by count and coloured by their mean";
    items.push({
      kind: "bubble",
      label: interactive ? `${bubble}. Zoom in or click one to see each asset` : bubble,
    });
    if (outside > 0) {
      const assets = `${count(outside)} ${outside === 1 ? "asset" : "assets"} outside any group`;
      items.push({
        kind: "text",
        label: interactive
          ? `${assets} ${outside === 1 ? "shows" : "show"} when you zoom in`
          : `${assets} ${outside === 1 ? "isn't" : "aren't"} drawn at this scale`,
      });
    }
  }
  return items;
}
