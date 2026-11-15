import { Link } from "react-router-dom";

import type { RunStatus } from "@/api/client";
import { useRuns } from "@/hooks/useRuns";
import { count } from "@/lib/format";

const STAGE_LABELS: Record<string, string> = {
  geolocating: "geolocating",
  classifying: "classifying",
  flood_zones: "looking up flood zones",
  assessing: "assessing",
};

/** Said in words, so a status never depends on its colour. */
function statusText(run: RunStatus): string {
  switch (run.status) {
    case "completed":
      return "Results ready";
    case "queued":
      return run.queue_position != null
        ? `Waiting to start (number ${run.queue_position} in the queue)`
        : "Waiting to start";
    case "running": {
      const stage = run.stage ? STAGE_LABELS[run.stage] ?? run.stage : null;
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

export function PortfoliosPage() {
  const { runs, error, connectionLost } = useRuns();

  return (
    <section aria-labelledby="portfolios-heading" className="narrow">
      <div className="page-heading">
        <h1 id="portfolios-heading">Portfolios</h1>
        <Link to="/upload" className="button button-primary">
          New portfolio
        </Link>
      </div>
      <p className="lede">The climate risk results of every portfolio assessed here.</p>

      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!runs && !error && <p className="muted">Loading…</p>}
      {connectionLost && (
        <p className="notice notice-warning" role="status">
          Lost contact with the server. Trying again.
        </p>
      )}
      {runs?.length === 0 && (
        <div className="empty-state">
          <p>No portfolios yet.</p>
          <p>
            <Link to="/upload">Assess a portfolio</Link> to see its results here.
          </p>
        </div>
      )}
      {runs && runs.length > 0 && (
        <div className="table-scroll">
          <table className="portfolios">
            <thead>
              <tr>
                <th scope="col">Portfolio</th>
                <th scope="col">Assets</th>
                <th scope="col">Status</th>
                <th scope="col">Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <th scope="row">
                    <Link to={`/runs/${encodeURIComponent(run.run_id)}`}>
                      {run.source_name ?? "Untitled portfolio"}
                    </Link>
                  </th>
                  <td>{count(run.total_rows)}</td>
                  <td>
                    <span className={STATUS_CLASS[run.status] ?? "status muted"}>
                      {statusText(run)}
                    </span>
                    {(run.status === "failed" || run.status === "interrupted") && run.error && (
                      <span className="status-error">{run.error}</span>
                    )}
                  </td>
                  <td>
                    <time dateTime={run.created_at}>{created(run.created_at)}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
