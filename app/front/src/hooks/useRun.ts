import { useEffect, useState } from "react";

import { ApiError, getRun, type RunStatus } from "@/api/client";

export const POLL_INTERVAL_MS = 1500;
const FINISHED = new Set(["completed", "failed", "interrupted"]);

export const isFinished = (run: RunStatus) => FINISHED.has(run.status);

interface RunState {
  run: RunStatus | null;
  /** The run can't be loaded and polling has stopped, for example because it doesn't exist. */
  error: string | null;
  /** The last poll failed, but a later one may work. */
  connectionLost: boolean;
}

/** Follow a run until it finishes. A lost connection is retried, as a run can take many minutes. */
export function useRun(runId: string): RunState {
  const [state, setState] = useState<RunState>({ run: null, error: null, connectionLost: false });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setState({ run: null, error: null, connectionLost: false });

    async function poll() {
      try {
        const run = await getRun(runId, controller.signal);
        setState({ run, error: null, connectionLost: false });
        if (isFinished(run)) return;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          setState({ run: null, error: error.message, connectionLost: false });
          return;
        }
        setState((previous) => ({ ...previous, connectionLost: true }));
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [runId]);

  return state;
}
