import { useEffect, useState } from "react";

import { ApiError, listRuns, type RunStatus } from "@/api/client";
import { POLL_INTERVAL_MS, isFinished } from "@/hooks/useRun";

interface RunsState {
  runs: RunStatus[] | null;
  /** The list couldn't be loaded at all. */
  error: string | null;
  /** A later poll failed, so the list shown may be out of date. */
  connectionLost: boolean;
}

/** Load every run, and keep polling only while one of them is queued or running. */
export function useRuns(): RunsState {
  const [state, setState] = useState<RunsState>({ runs: null, error: null, connectionLost: false });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let loaded = false;

    async function poll() {
      try {
        const runs = await listRuns(controller.signal);
        loaded = true;
        setState({ runs, error: null, connectionLost: false });
        if (runs.every(isFinished)) return;
      } catch (error) {
        if (controller.signal.aborted) return;
        const message = error instanceof ApiError ? error.message : "The portfolios didn't load.";
        // Before the first list there's nothing to keep showing, so stop and say why.
        if (!loaded) {
          setState({ runs: null, error: message, connectionLost: false });
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
  }, []);

  return state;
}
