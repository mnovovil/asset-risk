import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TrajectoryPoint } from "@/api/client";
import { trajectorySeries } from "@/lib/dashboard";
import { joinList, percent, percentTick, scenarioLabel } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";

import { ChartLegend } from "./ChartLegend";
import { ChartTooltip } from "./ChartTooltip";

const BASELINE_COLOR = "var(--series-other)";
// Fixed per scenario, whichever ones are configured. The two default scenarios get the first two
// slots, which are the easiest pair to tell apart.
const SCENARIO_COLORS: Record<string, string> = {
  ssp245: "var(--series-1)",
  ssp585: "var(--series-2)",
  ssp126: "var(--series-3)",
  ssp370: "var(--series-4)",
};
const scenarioColor = (scenario: string) => SCENARIO_COLORS[scenario] ?? BASELINE_COLOR;

interface TrajectoryProps {
  trajectory: TrajectoryPoint[];
  sharedHazards: string[];
}

export function Trajectory({ trajectory, sharedHazards }: TrajectoryProps) {
  const { scenarios, data } = trajectorySeries(trajectory);

  if (sharedHazards.length === 0 || data.length === 0) {
    return (
      <section className="panel" aria-labelledby="trajectory-heading">
        <h2 id="trajectory-heading">Change over time</h2>
        <p className="panel-note">
          These scenarios have no hazards in common, so they can't be compared.
        </p>
      </section>
    );
  }

  return (
    <section className="panel" aria-labelledby="trajectory-heading">
      <h2 id="trajectory-heading">Change over time</h2>
      <p className="panel-note">
        Mean annual loss over the hazards every scenario has, so the lines can be compared:{" "}
        {joinList(sharedHazards.map(hazardLabel))}. This can differ from the total above.
      </p>
      <div
        className="chart-frame"
        role="img"
        aria-label="Lines of mean annual loss by year for each scenario. The table below has the same values."
      >
        <ResponsiveContainer width="100%" height={280}>
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
            <YAxis
              domain={[0, "auto"]}
              width={64}
              tickFormatter={percentTick}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
            />
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
                      value: percent(item.value as number | null),
                      color: String(item.color),
                    }))}
                  />
                );
              }}
            />
            <Line
              dataKey="historical"
              name="Historical"
              stroke={BASELINE_COLOR}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            {scenarios.map((scenario) => (
              <Line
                key={scenario}
                dataKey={scenario}
                name={scenarioLabel(scenario)}
                stroke={scenarioColor(scenario)}
                strokeWidth={2}
                dot={{ r: 4, stroke: "var(--card)", strokeWidth: 2, fill: scenarioColor(scenario) }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          { key: "historical", label: "Historical", color: BASELINE_COLOR, kind: "line" },
          ...scenarios.map((scenario) => ({
            key: scenario,
            label: scenarioLabel(scenario),
            color: scenarioColor(scenario),
            kind: "line" as const,
          })),
        ]}
      />
      <details className="twin">
        <summary>Show as a table</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Year</th>
                <th scope="col">Historical</th>
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
                  <td>{percent(datum.historical)}</td>
                  {scenarios.map((scenario) => (
                    <td key={scenario}>{percent(datum[scenario])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="panel-note">
        Be careful reading this as a trend. River flood comes from a single climate model, so changes
        between years may be model noise, and there's no range to show how uncertain they are.
      </p>
    </section>
  );
}
