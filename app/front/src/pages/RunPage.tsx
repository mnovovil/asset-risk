import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { exportUrl, getSummary, type RunStatus, type Summary } from "@/api/client";
import { RunProgress } from "@/components/RunProgress";
import { useRun } from "@/hooks/useRun";

function CompletedRun({ run }: { run: RunStatus }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getSummary(run.run_id, controller.signal)
      .then(setSummary)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [run.run_id]);

  return (
    <>
      <p className="notice notice-success" role="status">
        This run has finished.
      </p>
      {failed && (
        <p className="notice notice-error" role="alert">
          The results couldn't be loaded.
        </p>
      )}
      {summary && (
        <p>
          {summary.assessable.toLocaleString()} of {summary.total_assets.toLocaleString()} assets
          were assessed, and {summary.excluded.toLocaleString()} were excluded.
        </p>
      )}
      <a className="button" href={exportUrl(run.run_id)}>
        Download results as CSV
      </a>
    </>
  );
}

export function RunPage() {
  const { runId = "" } = useParams();
  const { run, error, connectionLost } = useRun(runId);

  return (
    <section aria-labelledby="run-heading">
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
      {run?.status === "completed" && <CompletedRun run={run} />}
      {(run?.status === "failed" || run?.status === "interrupted") && (
        <p className="notice notice-error" role="alert">
          {run.error ?? "This run didn't finish."}
        </p>
      )}
    </section>
  );
}
