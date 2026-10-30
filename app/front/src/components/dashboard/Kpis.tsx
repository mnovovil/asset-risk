import type { Summary, TrajectoryPoint } from "@/api/client";
import { assumedShare, type AssetRow } from "@/lib/dashboard";
import { count, percent, plural } from "@/lib/format";

interface KpisProps {
  summary: Summary;
  point: TrajectoryPoint | undefined;
  rows: AssetRow[];
}

export function Kpis({ summary, point, rows }: KpisProps) {
  const assumed = assumedShare(summary.assessable, summary.assumed_type);
  const withHistorical = rows.filter((row) => row.historical !== null);
  const historicalMean = withHistorical.length
    ? withHistorical.reduce((sum, row) => sum + (row.historical as number), 0) /
      withHistorical.length
    : null;

  return (
    <dl className="kpis">
      <div className="kpi">
        <dt>Mean annual loss, equal-weighted</dt>
        <dd>
          <span className="kpi-value">{percent(point?.mean_total_aal)}</span>
          <span className="kpi-note">
            of asset value, over {plural(point?.hazards ?? 0, "hazard")}. Historical, same hazards:{" "}
            {percent(historicalMean)}
          </span>
        </dd>
      </div>
      <div className="kpi">
        <dt>Assets assessed</dt>
        <dd>
          <span className="kpi-value">
            {count(summary.assessable)} of {count(summary.total_assets)}
          </span>
          {summary.failed_assets > 0 && (
            <span className="kpi-note">
              {plural(summary.failed_assets, "asset")} missing some results
            </span>
          )}
        </dd>
      </div>
      <div className="kpi">
        <dt>Assets excluded</dt>
        <dd>
          <span className="kpi-value">{count(summary.excluded)}</span>
          <span className="kpi-note">Invalid, off land or no damage model</span>
        </dd>
      </div>
      <div className="kpi">
        <dt>Building type assumed</dt>
        <dd>
          <span className="kpi-value">{Math.round(assumed * 100)}%</span>
          <span className="kpi-note">
            {plural(summary.assumed_type, "asset")} had no building type to use
          </span>
        </dd>
      </div>
    </dl>
  );
}
