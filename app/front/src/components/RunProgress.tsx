import type { RunStatus } from "@/api/client";

const STAGES = [
  { key: "geolocating", label: "Geolocating", detail: "Matching points to buildings" },
  { key: "classifying", label: "Classifying", detail: "Working out each asset's type and region" },
  { key: "assessing", label: "Assessing", detail: "Calculating climate risk" },
];

export function RunProgress({ run }: { run: RunStatus }) {
  if (run.status === "queued") {
    return (
      <p>
        Waiting to start
        {run.queue_position != null && ` (number ${run.queue_position} in the queue)`}.
      </p>
    );
  }

  const current = STAGES.findIndex((stage) => stage.key === run.stage);
  return (
    <ol className="stages">
      {STAGES.map((stage, index) => {
        const state = index < current ? "done" : index === current ? "current" : "waiting";
        return (
          <li key={stage.key} className={`stage stage-${state}`}>
            <span className="stage-label" aria-current={state === "current" ? "step" : undefined}>
              {stage.label}
            </span>
            {state === "current" && <span className="muted">{stage.detail}</span>}
            {state === "current" && run.total > 0 && (
              <progress value={run.done} max={run.total} aria-label={`${stage.label} progress`}>
                {run.done} of {run.total}
              </progress>
            )}
          </li>
        );
      })}
    </ol>
  );
}
