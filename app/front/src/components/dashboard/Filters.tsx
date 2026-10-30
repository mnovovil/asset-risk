import { exportUrl, type Pair, type TrajectoryPoint } from "@/api/client";
import { scenariosOf, yearsOf } from "@/lib/dashboard";
import { hazardLabel } from "@/lib/hazards";
import { scenarioLabel } from "@/lib/format";

export const COLOR_BY_TOTAL = "total";

interface FiltersProps {
  runId: string;
  trajectory: TrajectoryPoint[];
  pair: Pair;
  onPairChange: (pair: Pair) => void;
  hazards: string[];
  colorBy: string;
  onColorByChange: (value: string) => void;
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
}: FiltersProps) {
  const years = yearsOf(trajectory, pair.scenario);
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
            const options = yearsOf(trajectory, scenario);
            const year = options.includes(pair.year as number) ? pair.year : options[0];
            onPairChange({ scenario, year });
          }}
        >
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
          onChange={(event) =>
            onPairChange({ scenario: pair.scenario, year: Number(event.target.value) })
          }
        >
          {years.map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </select>
      </label>
      <label>
        Colour the map by
        <select value={colorBy} onChange={(event) => onColorByChange(event.target.value)}>
          <option value={COLOR_BY_TOTAL}>Total annual loss</option>
          {hazards.map((hazard) => (
            <option key={hazard} value={hazard}>
              {hazardLabel(hazard)} score
            </option>
          ))}
        </select>
      </label>
      <a className="button" href={exportUrl(runId)}>
        Download results as CSV
      </a>
    </div>
  );
}
