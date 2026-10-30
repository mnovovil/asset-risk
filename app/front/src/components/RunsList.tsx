import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listRuns, type RunStatus } from "@/api/client";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  interrupted: "Interrupted",
};

export function RunsList() {
  const [runs, setRuns] = useState<RunStatus[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listRuns(controller.signal)
      .then(setRuns)
      // The list is a convenience: uploading still works without it.
      .catch(() => setRuns([]));
    return () => controller.abort();
  }, []);

  if (!runs || runs.length === 0) return null;

  return (
    <section aria-labelledby="past-runs">
      <h2 id="past-runs">Past runs</h2>
      <ul className="runs-list">
        {runs.map((run) => (
          <li key={run.run_id}>
            <Link to={`/runs/${run.run_id}`}>{run.source_name ?? "Portfolio"}</Link>
            <span className="muted">
              {run.total_rows.toLocaleString()} {run.total_rows === 1 ? "row" : "rows"} ·{" "}
              {new Date(run.created_at).toLocaleString()}
            </span>
            <span className={`status status-${run.status}`}>
              {STATUS_LABELS[run.status] ?? run.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
