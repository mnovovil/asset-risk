import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  ApiError,
  getAsset,
  getHazardCurve,
  type AssetDetail,
  type HazardCurve,
  type Pair,
} from "@/api/client";
import { SCORE_NOTES, scoreKind } from "@/lib/dashboard";
import { assetLabel, percent, scenarioLabel } from "@/lib/format";
import { hazardLabel, sortHazards } from "@/lib/hazards";

import { ChartLegend } from "./ChartLegend";
import { ChartTooltip } from "./ChartTooltip";

const HISTORICAL: Pair = { scenario: "historical", year: null };
const HISTORICAL_COLOR = "var(--series-other)";
const SCENARIO_COLOR = "var(--series-1)";

function matchText(asset: AssetDetail): string {
  switch (asset.match_type) {
    case "intersects":
      return "The point is inside this building";
    case "nearest":
      return `Nearest building, ${asset.distance_m ?? "?"} m away. It may be a neighbour.`;
    case "none":
      return "No building found within range";
    default:
      return "The row is invalid";
  }
}

function typeText(asset: AssetDetail): string {
  switch (asset.type_source) {
    case "class":
      return `From the Overture class "${asset.class}"`;
    case "subtype":
      return `From the Overture subtype "${asset.subtype}"`;
    case "assumed":
      return "Assumed: Overture has no usable type here. Results can move if this is wrong.";
    default:
      return "Not assessed";
  }
}

const EXCLUSIONS: Record<string, string> = {
  invalid: "Excluded: the id, latitude or longitude is missing or invalid.",
  off_land: "Excluded: no building found, and not near any country.",
  no_curve: "Excluded: physrisk has no damage model for this building type and region.",
};

function HazardCurveChart({ runId, rowNum, pair }: { runId: string; rowNum: number; pair: Pair }) {
  const [curves, setCurves] = useState<{ historical: HazardCurve; scenario: HazardCurve } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const { scenario, year } = pair;

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setCurves(null);
    setError(null);
    Promise.all([
      getHazardCurve(runId, rowNum, HISTORICAL, signal),
      getHazardCurve(runId, rowNum, { scenario, year }, signal),
    ])
      .then(([historical, selected]) => setCurves({ historical, scenario: selected }))
      .catch((e: unknown) => {
        if (signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "The hazard curve couldn't be loaded.");
      });
    return () => controller.abort();
  }, [runId, rowNum, scenario, year]);

  if (error) return <p className="notice notice-warning">{error}</p>;
  if (!curves) return <p className="muted">Loading…</p>;

  const name = `${scenarioLabel(scenario)}, ${year}`;
  const periods = sortedPeriods(curves.historical, curves.scenario);
  if (periods.length === 0) return <p className="muted">No river flood data at this location.</p>;
  const lookup = (curve: HazardCurve, period: number) => {
    const index = curve.return_periods.indexOf(period);
    return index === -1 ? null : curve.intensities[index];
  };
  const data = periods.map((period) => ({
    period,
    historical: lookup(curves.historical, period),
    scenario: lookup(curves.scenario, period),
  }));
  const depth = (value: number | null) => (value === null ? "–" : `${value.toFixed(2)} m`);

  return (
    <>
      <div
        className="chart-frame"
        role="img"
        aria-label="Lines of river flood depth by return period. The table below has the same values."
      >
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="period"
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              label={{
                value: "Return period (years)",
                position: "insideBottom",
                offset: -2,
                fill: "var(--muted)",
                fontSize: 12,
              }}
              height={40}
            />
            <YAxis
              width={60}
              domain={[0, "auto"]}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              tickFormatter={(value: number) => `${value} m`}
            />
            <Tooltip
              cursor={{ stroke: "var(--axis)" }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <ChartTooltip
                    title={`1 in ${label} years`}
                    rows={payload.map((item) => ({
                      key: String(item.dataKey),
                      label: String(item.name),
                      value: depth(item.value as number | null),
                      color: String(item.color),
                    }))}
                  />
                );
              }}
            />
            <Line
              dataKey="historical"
              name="Historical"
              stroke={HISTORICAL_COLOR}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="scenario"
              name={name}
              stroke={SCENARIO_COLOR}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          { key: "historical", label: "Historical", color: HISTORICAL_COLOR, kind: "line" },
          { key: "scenario", label: name, color: SCENARIO_COLOR, kind: "line" },
        ]}
      />
      <details className="twin">
        <summary>Show as a table</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Return period</th>
                <th scope="col">Historical</th>
                <th scope="col">{name}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((datum) => (
                <tr key={datum.period}>
                  <th scope="row">{datum.period} years</th>
                  <td>{depth(datum.historical)}</td>
                  <td>{depth(datum.scenario)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

const sortedPeriods = (...curves: HazardCurve[]) =>
  [...new Set(curves.flatMap((curve) => curve.return_periods))].sort((a, b) => a - b);

interface AssetPanelProps {
  runId: string;
  rowNum: number;
  pair: Pair;
  onClose: () => void;
}

export function AssetPanel({ runId, rowNum, pair, onClose }: AssetPanelProps) {
  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    setAsset(null);
    setError(null);
    getAsset(runId, rowNum, controller.signal)
      .then(setAsset)
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "This asset couldn't be loaded.");
      });
    return () => controller.abort();
  }, [runId, rowNum]);

  const matches = (item: { scenario: string; year: number | null }) =>
    item.scenario === pair.scenario && item.year === pair.year;
  const impacts = asset?.impacts.filter(matches) ?? [];
  const scores = asset?.scores.filter(matches) ?? [];
  const hazards = sortHazards([...impacts.map((i) => i.hazard), ...scores.map((s) => s.hazard)]);

  return (
    <aside className="asset-panel" role="dialog" aria-label="Asset details">
      <div className="asset-panel-header">
        <h2>{asset ? assetLabel(asset) : "Asset"}</h2>
        <button ref={closeButton} type="button" className="button" onClick={onClose}>
          Close
        </button>
      </div>
      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!asset && !error && <p className="muted">Loading…</p>}
      {asset && (
        <>
          {asset.exclusion_reason && (
            <p className="notice notice-warning">
              {EXCLUSIONS[asset.exclusion_reason] ?? `Excluded: ${asset.exclusion_reason}`}
            </p>
          )}
          <h3>Building</h3>
          <dl>
            <dt>Match</dt>
            <dd>{matchText(asset)}</dd>
            <dt>Name</dt>
            <dd>{asset.name ?? "–"}</dd>
            <dt>Class</dt>
            <dd>{asset.class ?? "–"}</dd>
            <dt>Subtype</dt>
            <dd>{asset.subtype ?? "–"}</dd>
            <dt>Height</dt>
            <dd>{asset.height === null ? "–" : `${asset.height} m`}</dd>
            <dt>Floors</dt>
            <dd>{asset.num_floors ?? "–"}</dd>
            <dt>Location</dt>
            <dd>
              {asset.lat ?? "–"}, {asset.lon ?? "–"}
            </dd>
          </dl>
          <p className="panel-note">Height and floors are shown for context. They don't affect the results.</p>
          <h3>How it was modelled</h3>
          <dl>
            <dt>Type</dt>
            <dd>{asset.physrisk_type ?? "–"}</dd>
            <dt>Decided by</dt>
            <dd>{typeText(asset)}</dd>
            <dt>Region</dt>
            <dd>
              {asset.physrisk_location ?? "–"}
              {asset.location_fallback &&
                ` (physrisk has no ${asset.region} model for this type, so this uses its global one)`}
            </dd>
          </dl>
          {asset.assessable && (
            <>
              <h3>
                Results for {scenarioLabel(pair.scenario)}, {pair.year}
              </h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Hazard</th>
                      <th scope="col">Annual loss</th>
                      <th scope="col">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hazards.map((hazard) => {
                      const impact = impacts.find((i) => i.hazard === hazard);
                      const score = scores.find((s) => s.hazard === hazard);
                      const kind = score ? scoreKind(score.score) : null;
                      return (
                        <tr key={hazard}>
                          <th scope="row">{hazardLabel(hazard)}</th>
                          <td>{impact ? percent(impact.aal) : "–"}</td>
                          <td className={kind === "scored" ? "" : "score-none"}>
                            {kind === "scored"
                              ? score?.label
                              : kind
                                ? SCORE_NOTES[kind]
                                : "Not returned"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <h3>River flood depth</h3>
              <HazardCurveChart runId={runId} rowNum={rowNum} pair={pair} />
              <p className="panel-note">
                Raw hazard data, before any assumed flood protection. A flat line at zero means this
                exact point is dry in the data, not that the area has no flood risk.
              </p>
            </>
          )}
        </>
      )}
    </aside>
  );
}
