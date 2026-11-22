/**
 * What the PDF report says, from what the dashboard already has. No DOM and no PDF library here, so
 * it's testable; components/report draws it.
 */

import type { Pair } from "@/api/client";
import type { RunData } from "@/hooks/useDashboard";
import {
  type AssetRow,
  isBaseline,
  type KpiItem,
  valueCoverage,
  type Weighting,
  kpiItems,
  pairLabel,
  pointFor,
  typeSourceCounts,
} from "@/lib/dashboard";
import { count } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { clusteredRowNums } from "@/lib/clusters";
import { COLOR_BY_EXPECTED_LOSS, COLOR_BY_TOTAL, placeable } from "@/lib/mapFeatures";
import { type LegendItem, mapLegend } from "@/lib/mapLegend";
import { type NoteGroup, REPORT_NOTES, REPORT_SOURCE_NOTE } from "@/lib/reportText";

export interface ReportInput {
  /** The uploaded file's name, which can contain any character. */
  label: string | null;
  createdAt: string;
  generatedAt: Date;
  pair: Pair;
  colorBy: string;
  /** How portfolio figures are averaged, as the dashboard showed them. */
  weighting?: Weighting;
  run: RunData;
  rows: AssetRow[];
  /** The building type assumed when Overture says nothing, if known. */
  defaultType: string | null;
}

export interface ReportFact {
  label: string;
  value: string;
}

export interface ReportContent {
  title: string;
  facts: ReportFact[];
  kpis: KpiItem[];
  /** Where building types came from, so an assumed type is never hidden. */
  typeSource: string;
  map: { heading: string; caption: string; legend: LegendItem[] };
  /** null when there are charts to show; otherwise why there aren't. */
  noResults: string | null;
  notes: NoteGroup[];
  sourceNote: string;
  footer: string;
}

/** A date-time as YYYY-MM-DD, in UTC, so a report reads the same wherever it's made. */
const day = (value: Date | string) => new Date(value).toISOString().slice(0, 10);

export function colorByLabel(colorBy: string): string {
  if (colorBy === COLOR_BY_TOTAL) return "Total annual loss";
  if (colorBy === COLOR_BY_EXPECTED_LOSS) return "Expected annual loss";
  return `${hazardLabel(colorBy)} score`;
}

export function weightingLabel(weighting: Weighting, currency: string | null): string {
  if (weighting === "equal") return "Equal: every asset counts the same";
  return `By value${currency ? `, in ${currency}` : ", in the file's value units"}`;
}

export function reportContent(input: ReportInput): ReportContent {
  const { run, rows, pair, colorBy } = input;
  const weighting = run.summary.has_values ? (input.weighting ?? "equal") : "equal";
  const currency = run.summary.currency ?? null;
  const point = pointFor(run.trajectory, pair);
  const baseline = isBaseline(pair);
  const sources = typeSourceCounts(run.assets);
  const assumed = input.defaultType
    ? `assumed as ${input.defaultType}: ${count(sources.assumed)}`
    : `assumed: ${count(sources.assumed)}`;
  const hasClusters = run.clusters.length > 0;
  const clustered = clusteredRowNums(run.clusters);
  const outside = hasClusters
    ? placeable(run.assets).filter((a) => !clustered.has(a.row_num)).length
    : 0;

  let noResults: string | null = null;
  if (rows.length === 0) {
    noResults =
      run.summary.assessable === 0
        ? "No asset in this portfolio could be assessed."
        : "This scenario has no results.";
  }

  return {
    title: input.label?.trim() || "Portfolio run",
    facts: [
      { label: "Scenario", value: pairLabel(pair) },
      { label: "Run date", value: day(input.createdAt) },
      { label: "Assets", value: count(run.summary.total_assets) },
      { label: "Map coloured by", value: colorByLabel(colorBy) },
      ...(run.summary.has_values
        ? [
            { label: "Weighting", value: weightingLabel(weighting, currency) },
            ...(weighting === "value"
              ? [{ label: "Value coverage", value: valueCoverage(run.summary, point) }]
              : []),
          ]
        : []),
    ],
    kpis: kpiItems(run.summary, point, rows, baseline, weighting),
    typeSource:
      `Building type of assessed assets, from Overture's class: ${count(sources.class)}, ` +
      `from its subtype: ${count(sources.subtype)}, ${assumed}.`,
    map: {
      heading: "Where the risk is",
      caption: hasClusters
        ? "The portfolio as the dashboard map opens, with nearby assets grouped into bubbles."
        : "The portfolio as the dashboard map opens.",
      legend: mapLegend({
        rows,
        colorBy,
        hasClusters,
        outside,
        dark: false,
        interactive: false,
        currency,
      }),
    },
    noResults,
    notes: REPORT_NOTES,
    sourceNote: REPORT_SOURCE_NOTE,
    footer: `${input.label?.trim() || "Portfolio run"} · ${pairLabel(pair)} · generated ${day(input.generatedAt)} by asset-risk`,
  };
}

const MAX_SLUG = 60;

/** Safe on every file system: ASCII letters, digits and hyphens, whatever the label holds. */
export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "") // accents, once split off their letters
    .replace(/\.csv$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_SLUG)
    .replace(/-+$/, "");
}

export function reportFileName(label: string | null, pair: Pair): string {
  const name = slugify(label ?? "") || "portfolio";
  const when = isBaseline(pair) ? "baseline" : `${slugify(pair.scenario) || "scenario"}_${pair.year}`;
  return `asset-risk_${name}_${when}.pdf`;
}

// Countries that use US Letter rather than A4.
const LETTER_REGIONS = new Set(["US", "CA", "MX", "PH", "CL", "CO", "VE", "GT", "CR", "PR"]);

/** Letter where it's the norm, A4 elsewhere. The layout fits both. */
export function pageFormat(locale: string | undefined): "a4" | "letter" {
  if (!locale) return "a4";
  try {
    const region = new Intl.Locale(locale).maximize().region;
    return region && LETTER_REGIONS.has(region) ? "letter" : "a4";
  } catch {
    return "a4";
  }
}
