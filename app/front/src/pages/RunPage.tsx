import { Link, useParams } from "react-router-dom";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { RunProgress } from "@/components/RunProgress";
import { useRun } from "@/hooks/useRun";

export function RunPage() {
  const { runId = "" } = useParams();
  const { run, error, connectionLost } = useRun(runId);

  return (
    <section aria-labelledby="run-heading" className={run?.status === "completed" ? "" : "narrow"}>
      <p>
        <Link to="/">← New portfolio</Link>
      </p>
      <h1 id="run-heading">{run?.source_name ?? "Portfolio run"}</h1>
      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!run && !error && <p className="muted">Loading…</p>}
      {connectionLost && (
        <p className="notice notice-warning" role="status">
          Lost contact with the server. Trying again.
        </p>
      )}
      {run && (run.status === "queued" || run.status === "running") && <RunProgress run={run} />}
      {run?.status === "completed" && <Dashboard runId={run.run_id} />}
      {(run?.status === "failed" || run?.status === "interrupted") && (
        <p className="notice notice-error" role="alert">
          {run.error ?? "This run didn't finish."}
        </p>
      )}
    </section>
  );
}
