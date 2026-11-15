import { lazy, Suspense, useRef } from "react";
import { Link } from "react-router-dom";

import type { RunStatus } from "@/api/client";
import { useInView } from "@/hooks/useInView";
import { usePortfolioCard } from "@/hooks/usePortfolioCard";
import { assumedShare, pairLabel, pointFor } from "@/lib/dashboard";
import { count, percent, plural } from "@/lib/format";

const loading = <div className="card-map-placeholder card-map-loading" aria-hidden="true" />;

// MapLibre is large, so it loads only once a card has a map to draw.
const RiskMapThumbnail = lazy(() => import("@/components/portfolios/RiskMapThumbnail"));

/** Past this share, the assumption shapes results more than the data does, as in DataQuality. */
const ASSUMED_WARNING_SHARE = 0.5;

const STAGE_LABELS: Record<string, string> = {
  geolocating: "geolocating",
  classifying: "classifying",
  flood_zones: "looking up flood zones",
  assessing: "assessing",
};

/** Said in words, so a status never depends on its colour. */
export function statusText(run: RunStatus): string {
  switch (run.status) {
    case "completed":
      return "Results ready";
    case "queued":
      return run.queue_position != null
        ? `Waiting to start (number ${run.queue_position} in the queue)`
        : "Waiting to start";
    case "running": {
      const stage = run.stage ? (STAGE_LABELS[run.stage] ?? run.stage) : null;
      const progress = run.total > 0 ? ` (${count(run.done)} of ${count(run.total)})` : "";
      return stage ? `Running: ${stage}${progress}` : "Running";
    }
    case "failed":
      return "Failed";
    case "interrupted":
      return "Didn't finish";
    default:
      return run.status;
  }
}

const STATUS_CLASS: Record<string, string> = {
  completed: "status status-completed",
  failed: "status status-failed",
  interrupted: "status status-failed",
};

const created = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card-figure">
      <dt>{label}</dt>
      <dd>
        <span className="card-figure-value">{value}</span>
        {note && <span className="card-figure-note">{note}</span>}
      </dd>
    </div>
  );
}

/** The four figures the dashboard opens with, for the same scenario and year. */
function Results({ run }: { run: RunStatus }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const { data, error } = usePortfolioCard(run.run_id, inView);
  const name = run.source_name ?? "Untitled portfolio";

  let body;
  if (error) {
    body = (
      <p className="card-message" role="status">
        {error}
      </p>
    );
  } else if (!data) {
    body = <p className="card-message muted">Loading results…</p>;
  } else {
    const { overview, pair, totals } = data;
    const { summary } = overview;
    const point = pair ? pointFor(overview.trajectory, pair) : undefined;
    const hasLoss = point != null && point.assets > 0 && point.mean_total_aal != null;
    const assumed = assumedShare(summary.assessable, summary.assumed_type);
    const placed = overview.points.length;
    const warn = assumed > ASSUMED_WARNING_SHARE;
    const where = `Map of where ${name}'s ${plural(placed, "asset")} are`;
    const alt = `${where}, coloured by total annual loss`;
    body = (
      <>
        <div className="card-map">
          {placed > 0 ? (
            <Suspense fallback={loading}>
              <RiskMapThumbnail
                runId={run.run_id}
                points={overview.points}
                clusters={overview.clusters}
                totals={totals}
                alt={alt}
              />
            </Suspense>
          ) : (
            <p className="card-map-placeholder">No asset could be placed on a map.</p>
          )}
        </div>
        <dl className="card-figures">
          <Figure
            label="Mean annual loss, equal-weighted"
            value={hasLoss ? percent(point.mean_total_aal) : "No results"}
            note={
              pair && point
                ? `${pairLabel(pair)}, over ${plural(point.hazards, "hazard")}`
                : "No future scenario was assessed"
            }
          />
          <Figure
            label="Assets assessed"
            value={`${count(summary.assessable)} of ${count(summary.total_assets)}`}
            note={
              summary.failed_assets > 0
                ? `${plural(summary.failed_assets, "asset")} missing some results`
                : undefined
            }
          />
          <Figure
            label="Assets excluded"
            value={count(summary.excluded)}
            note="Invalid, off land or no damage model"
          />
          <div className={warn ? "card-figure card-figure-warning" : "card-figure"}>
            <dt>Building type assumed</dt>
            <dd>
              <span className="card-figure-value">{Math.round(assumed * 100)}%</span>
              <span className="card-figure-note">
                {warn
                  ? "Most types were assumed, so results can move materially"
                  : `${plural(summary.assumed_type, "asset")} had no building type to use`}
              </span>
            </dd>
          </div>
        </dl>
      </>
    );
  }

  return (
    <div ref={ref} className="card-results">
      {body}
    </div>
  );
}

/** A run that has no results yet, or never will: what's happening, where the map would be. */
function Pending({ run }: { run: RunStatus }) {
  const failed = run.status === "failed" || run.status === "interrupted";
  return (
    <div className="card-map card-map-pending">
      <div className="card-pending">
        <span className={STATUS_CLASS[run.status] ?? "status"}>{statusText(run)}</span>
        {run.status === "running" && run.total > 0 && (
          <progress value={run.done} max={run.total} aria-label="Progress in this stage" />
        )}
        {failed && run.error && <span className="status-error">{run.error}</span>}
      </div>
    </div>
  );
}

export function PortfolioCard({ run }: { run: RunStatus }) {
  const completed = run.status === "completed";
  return (
    <article className="portfolio-card">
      <header className="card-header">
        <h2 className="card-title">
          {/* One link, stretched over the whole card, so it's one stop for the keyboard. */}
          <Link to={`/runs/${encodeURIComponent(run.run_id)}`} className="card-link">
            {run.source_name ?? "Untitled portfolio"}
          </Link>
        </h2>
        <p className="card-meta">
          {plural(run.total_rows, "asset")} ·{" "}
          <time dateTime={run.created_at}>{created(run.created_at)}</time>
          {completed && (
            <>
              {" · "}
              <span className={STATUS_CLASS.completed}>{statusText(run)}</span>
            </>
          )}
        </p>
      </header>
      {completed ? <Results run={run} /> : <Pending run={run} />}
    </article>
  );
}
