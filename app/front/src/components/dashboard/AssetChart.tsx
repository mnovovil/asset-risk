import { useId, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AssetDetail, Pair } from "@/api/client";
import {
  assetChartOptions,
  assetSeries,
  BASELINE_LABEL,
  isBaseline,
  pairLabel,
  SCORE_NOTES,
} from "@/lib/dashboard";
import { joinList, percent, percentTick, scenarioLabel } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { SCORE_LABELS } from "@/lib/mapColors";
import { BASELINE_COLOR, scenarioColor } from "@/lib/scenarios";

import { ChartLegend } from "./ChartLegend";
import { ChartTooltip } from "./ChartTooltip";

const ZERO_SCALE = 0.01;

const scoreText = (value: number | null) => (value === null ? "–" : SCORE_LABELS[value]);

interface AssetChartProps {
  asset: Pick<AssetDetail, "impacts" | "scores">;
  pair: Pair;
  /** The run's scenarios, so one with nothing for a hazard can be named. */
  scenarios: string[];
}

/** One asset's annual loss or score for one hazard, over the years and scenarios of the run. */
export function AssetChart({ asset, pair, scenarios: runScenarios }: AssetChartProps) {
  const selectId = useId();
  const options = assetChartOptions(asset);
  const [selected, setSelected] = useState<string | null>(null);
  // Keep the choice while it exists for this asset, and fall back to the first chart otherwise.
  const current = options.find((option) => option.key === selected) ?? options[0];

  if (!current) return <p className="muted">No results for this asset.</p>;

  const { metric, hazard } = current;
  const loss = metric === "loss";
  const series = assetSeries(asset, metric, hazard, runScenarios);
  const { scenarios, data, baseline } = series;
  const format = loss ? percent : scoreText;
  const hazardName = hazardLabel(hazard);
  const highlighted = isBaseline(pair) ? null : pair;
  const showBaseline = loss && baseline !== null;
  // Recharts stretches an all-zero axis to 400%, so a chart of zeros gets a small fixed scale.
  const largest = Math.max(
    baseline ?? 0,
    ...data.flatMap((datum) => scenarios.map((scenario) => datum[scenario] ?? 0)),
  );

  const picker = (
    <div className="map-controls">
      <label htmlFor={selectId}>
        Chart
        <select id={selectId} value={current.key} onChange={(event) => setSelected(event.target.value)}>
          {options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );

  const notes = (
    <>
      {series.missingScenarios.length > 0 && (
        <p className="panel-note">
          No {hazardName.toLowerCase()} {loss ? "loss" : "score"} results for{" "}
          {joinList(series.missingScenarios.map(scenarioLabel))}.
        </p>
      )}
      {series.notes.length > 0 && (
        <p className="panel-note">
          Not scored:{" "}
          {joinList(series.notes.map((note) => `${pairLabel(note)} (${SCORE_NOTES[note.kind]})`))}
          . These are not low scores.
        </p>
      )}
      <p className="panel-note">
        {loss
          ? [
              "Expected annual loss as a share of the building's value.",
              showBaseline && `The flat dashed line is ${BASELINE_LABEL.toLowerCase()}, for reference.`,
            ]
              .filter(Boolean)
              .join(" ")
          : "physrisk scores scenarios only, so there is no baseline. A low score isn't proof of low risk: a point with little hazard data can still score Very low."}
      </p>
    </>
  );

  if (data.length === 0) {
    return (
      <>
        {picker}
        <p className="muted">
          No scenario results for {hazardName.toLowerCase()}
          {showBaseline ? `. ${BASELINE_LABEL}: ${percent(baseline)}.` : "."}
        </p>
        {notes}
      </>
    );
  }

  const legend = [
    ...(showBaseline
      ? [{ key: "historical", label: BASELINE_LABEL, color: BASELINE_COLOR, kind: "line" as const }]
      : []),
    ...scenarios.map((scenario) => ({
      key: scenario,
      label: scenarioLabel(scenario),
      color: scenarioColor(scenario),
      kind: "line" as const,
    })),
  ];

  return (
    <>
      {picker}
      <div
        className="chart-frame"
        role="img"
        aria-label={`Lines of ${hazardName.toLowerCase()} ${
          loss ? "annual loss" : "score"
        } by year for each scenario. The table below has the same values.`}
      >
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="year"
              type="number"
              domain={["dataMin", "dataMax"]}
              ticks={data.map((datum) => datum.year)}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              padding={{ left: 16, right: 16 }}
            />
            {loss ? (
              <YAxis
                domain={largest > 0 ? [0, "auto"] : [0, ZERO_SCALE]}
                width={64}
                tickFormatter={percentTick}
                stroke="var(--axis)"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
              />
            ) : (
              <YAxis
                type="number"
                domain={[0, SCORE_LABELS.length - 1]}
                ticks={SCORE_LABELS.map((_, index) => index)}
                allowDecimals={false}
                width={72}
                tickFormatter={(value: number) => SCORE_LABELS[value] ?? ""}
                stroke="var(--axis)"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
              />
            )}
            {highlighted?.year != null && (
              <ReferenceLine x={highlighted.year} stroke="var(--axis)" strokeDasharray="4 4" />
            )}
            <Tooltip
              cursor={{ stroke: "var(--axis)" }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <ChartTooltip
                    title={String(label)}
                    rows={payload.map((item) => ({
                      key: String(item.dataKey),
                      label: String(item.name),
                      value: format(item.value as number | null),
                      color: String(item.color),
                    }))}
                  />
                );
              }}
            />
            {showBaseline && (
              <Line
                dataKey="historical"
                name={BASELINE_LABEL}
                stroke={BASELINE_COLOR}
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                isAnimationActive={false}
              />
            )}
            {scenarios.map((scenario) => (
              <Line
                key={scenario}
                dataKey={scenario}
                name={scenarioLabel(scenario)}
                // Scores are steps, not a measured trend, so they aren't drawn as a slope.
                type={loss ? "linear" : "stepAfter"}
                stroke={scenarioColor(scenario)}
                strokeWidth={highlighted?.scenario === scenario ? 3 : 2}
                connectNulls={false}
                dot={{ r: 4, stroke: "var(--card)", strokeWidth: 2, fill: scenarioColor(scenario) }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend items={legend} />
      {highlighted && (
        <p className="panel-note">The dashed vertical line marks {pairLabel(highlighted)}.</p>
      )}
      {notes}
      <details className="twin">
        <summary>Show as a table</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Year</th>
                {showBaseline && <th scope="col">{BASELINE_LABEL}</th>}
                {scenarios.map((scenario) => (
                  <th key={scenario} scope="col">
                    {scenarioLabel(scenario)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((datum) => (
                <tr key={datum.year}>
                  <th scope="row">{datum.year}</th>
                  {showBaseline && <td>{percent(datum.historical)}</td>}
                  {scenarios.map((scenario) => (
                    <td key={scenario}>{format(datum[scenario])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
