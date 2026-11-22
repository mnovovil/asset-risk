import { exportUrl, type Pair, type TrajectoryPoint } from "@/api/client";
import {
  BASELINE,
  BASELINE_LABEL,
  hasBaseline,
  isBaseline,
  preferredYear,
  scenariosOf,
  type Weighting,
  yearsOf,
} from "@/lib/dashboard";
import { hazardLabel } from "@/lib/hazards";
import { scenarioLabel } from "@/lib/format";

import { COLOR_BY_EXPECTED_LOSS, COLOR_BY_TOTAL } from "@/lib/mapFeatures";
import { type ReportState, STAGE_TEXT } from "@/hooks/useReport";

export { COLOR_BY_TOTAL };

interface FiltersProps {
  runId: string;
  trajectory: TrajectoryPoint[];
  pair: Pair;
  onPairChange: (pair: Pair) => void;
  hazards: string[];
  colorBy: string;
  onColorByChange: (value: string) => void;
  /** Whether any asset has a usable value. Without one, there's nothing to weight by. */
  hasValues?: boolean;
  weighting?: Weighting;
  onWeightingChange?: (weighting: Weighting) => void;
  report: {
    state: ReportState;
    /** Why the report can't be made yet, or null when it can. */
    blocked: string | null;
    onDownload: () => void;
  };
}

/** One row above everything it scopes: every figure below follows these. */
export function Filters({
  runId,
  trajectory,
  pair,
  onPairChange,
  hazards,
  colorBy,
  onColorByChange,
  hasValues = false,
  weighting = "equal",
  onWeightingChange,
  report,
}: FiltersProps) {
  const years = yearsOf(trajectory, pair.scenario);
  const generating = report.state.kind === "generating";
  const hasResults = (scenario: string) =>
    trajectory.some((p) => p.scenario === scenario && p.assets > 0);

  return (
    <div className="filters">
      <label>
        Scenario
        <select
          value={pair.scenario}
          onChange={(event) => {
            const scenario = event.target.value;
            if (scenario === BASELINE.scenario) return onPairChange(BASELINE);
            const options = yearsOf(trajectory, scenario);
            const year = options.includes(pair.year as number) ? pair.year : preferredYear(options);
            onPairChange({ scenario, year: year ?? null });
          }}
        >
          {hasBaseline(trajectory) && (
            <option value={BASELINE.scenario}>{BASELINE_LABEL}</option>
          )}
          {scenariosOf(trajectory).map((scenario) => (
            <option key={scenario} value={scenario}>
              {scenarioLabel(scenario)}
              {hasResults(scenario) ? "" : " (no data)"}
            </option>
          ))}
        </select>
      </label>
      <label>
        Year
        <select
          value={pair.year ?? ""}
          disabled={isBaseline(pair)}
          onChange={(event) =>
            onPairChange({ scenario: pair.scenario, year: Number(event.target.value) })
          }
        >
          {isBaseline(pair) && <option value="">–</option>}
          {years.map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </select>
      </label>
      {hasValues && (
        <label>
          Weighting
          <select
            value={weighting}
            onChange={(event) => onWeightingChange?.(event.target.value as Weighting)}
          >
            <option value="equal">Equal</option>
            <option value="value">By value</option>
          </select>
        </label>
      )}
      <label>
        Colour the map by
        <select value={colorBy} onChange={(event) => onColorByChange(event.target.value)}>
          <option value={COLOR_BY_TOTAL}>Total annual loss</option>
          {hasValues && <option value={COLOR_BY_EXPECTED_LOSS}>Expected annual loss</option>}
          {hazards.map((hazard) => (
            <option key={hazard} value={hazard}>
              {hazardLabel(hazard)} score
            </option>
          ))}
        </select>
      </label>
      <div className="filters-downloads">
        <a className="button" href={exportUrl(runId)}>
          Download results as CSV
        </a>
        <button
          type="button"
          className="button"
          onClick={report.onDownload}
          disabled={report.blocked !== null || generating}
          aria-busy={generating}
          aria-describedby="report-status"
        >
          {generating ? "Preparing report…" : "Download report as PDF"}
        </button>
        <p id="report-status" className="report-status" aria-live="polite">
          {report.state.kind === "generating"
            ? `Preparing the PDF: ${STAGE_TEXT[report.state.stage]}…`
            : report.blocked}
        </p>
      </div>
    </div>
  );
}
