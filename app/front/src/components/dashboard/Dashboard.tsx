import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { getConfig, type Pair } from "@/api/client";
import { useRunData, usePairData } from "@/hooks/useDashboard";
import { useReport } from "@/hooks/useReport";
import { buildRows, defaultPair, isBaseline, missingHazards, pointFor, scenariosOf } from "@/lib/dashboard";
import { sortHazards } from "@/lib/hazards";

import { AssetPanel } from "./AssetPanel";
import { DataQuality } from "./DataQuality";
import { COLOR_BY_TOTAL, Filters } from "./Filters";
import { Kpis } from "./Kpis";
import { LossBars } from "./LossBars";
import { ScoreTable } from "./ScoreTable";
import { Trajectory } from "./Trajectory";

import type { MapStatus } from "./RiskMap";

// The map library is large, and the rest of the dashboard works without it.
const RiskMap = lazy(() => import("./RiskMap"));

interface DashboardProps {
  runId: string;
  /** The uploaded file's name, for the PDF report. Only ever a label. */
  label?: string | null;
  createdAt?: string;
}

const REPORT_BLOCKED: Record<Exclude<MapStatus, "ready">, string> = {
  loading: "Waiting for the map…",
  unavailable: "This browser can't draw the map, so it can't make the report.",
};

export function Dashboard({ runId, label = null, createdAt }: DashboardProps) {
  const { data: run, error: runError } = useRunData(runId);
  const [pair, setPair] = useState<Pair | null>(null);
  const [colorBy, setColorBy] = useState(COLOR_BY_TOTAL);
  const [selected, setSelected] = useState<number | null>(null);
  const [defaultType, setDefaultType] = useState<string | null>(null);
  const { data: results, loading, error: pairError } = usePairData(runId, pair);
  const closePanel = useCallback(() => setSelected(null), []);
  const [mapStatus, setMapStatus] = useState<MapStatus>("loading");
  const report = useReport();

  useEffect(() => {
    if (run && !pair) setPair(defaultPair(run.trajectory));
  }, [run, pair]);

  useEffect(() => {
    const controller = new AbortController();
    getConfig(controller.signal)
      .then((config) => setDefaultType(config.default_building_type))
      .catch(() => undefined); // only used to name the assumption
    return () => controller.abort();
  }, []);

  const baseline = isBaseline(pair);
  const rows = useMemo(
    () =>
      results && run
        ? // The baseline is never compared with itself.
          buildRows(results.totals, results.impacts, results.scores, baseline ? [] : run.historical)
        : [],
    [results, run, baseline],
  );
  const scoreHazards = useMemo(
    () => sortHazards((results?.scores ?? []).filter((s) => s.score >= 0).map((s) => s.hazard)),
    [results],
  );

  if (runError) {
    return (
      <p className="notice notice-error" role="alert">
        {runError}
      </p>
    );
  }
  if (!run || !pair) return <p className="muted">Loading results…</p>;

  const missing = missingHazards(run.coverage, pair);
  const point = pointFor(run.trajectory, pair);

  let reportBlocked: string | null = null;
  if (loading || !results) reportBlocked = "Waiting for results…";
  else if (mapStatus !== "ready") reportBlocked = REPORT_BLOCKED[mapStatus];

  const downloadReport = () =>
    report.generate({
      input: {
        label,
        createdAt: createdAt ?? new Date().toISOString(),
        generatedAt: new Date(),
        pair,
        colorBy,
        run,
        rows,
        defaultType,
      },
      missing,
      locale: navigator.language,
    });

  return (
    <>
      <Filters
        runId={runId}
        trajectory={run.trajectory}
        pair={pair}
        onPairChange={(next) => {
          setPair(next);
          setColorBy(COLOR_BY_TOTAL);
        }}
        hazards={scoreHazards}
        colorBy={colorBy}
        onColorByChange={setColorBy}
        report={{ state: report.state, blocked: reportBlocked, onDownload: downloadReport }}
      />
      {report.state.kind === "error" && (
        <p className="notice notice-error" role="alert">
          {report.state.message}
        </p>
      )}
      {pairError && (
        <p className="notice notice-error" role="alert">
          {pairError}
        </p>
      )}
      <div className="dashboard-body" aria-busy={loading}>
        <Kpis summary={run.summary} point={point} rows={rows} baseline={baseline} />
        <Suspense fallback={<p className="muted">Loading the map…</p>}>
          <RiskMap
            assets={run.assets}
            clusters={run.clusters}
            rows={rows}
            colorBy={colorBy}
            selected={selected}
            onSelect={setSelected}
            onStatusChange={setMapStatus}
          />
        </Suspense>
        {rows.length > 0 ? (
          <>
            <LossBars rows={rows} missing={missing} baseline={baseline} onSelect={setSelected} />
            <ScoreTable rows={rows} baseline={baseline} onSelect={setSelected} />
            <Trajectory trajectory={run.trajectory} sharedHazards={run.summary.shared_hazards} />
          </>
        ) : (
          !loading && (
            <p className="notice notice-warning">
              {run.summary.assessable === 0
                ? "No asset in this portfolio could be assessed. See why below."
                : "This scenario has no results. Try another one."}
            </p>
          )
        )}
        <DataQuality
          summary={run.summary}
          assets={run.assets}
          trajectory={run.trajectory}
          missing={missing}
          defaultType={defaultType}
          onSelect={setSelected}
        />
      </div>
      {selected !== null && (
        <AssetPanel
          runId={runId}
          rowNum={selected}
          pair={pair}
          scenarios={scenariosOf(run.trajectory)}
          onClose={closePanel}
        />
      )}
    </>
  );
}
