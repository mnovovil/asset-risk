import { useCallback, useEffect, useRef, useState } from "react";

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
export function useRuns(): RunsState & { remove: (runId: string) => void } {
  const [state, setState] = useState<RunsState>({ runs: null, error: null, connectionLost: false });
  // Deleted here, so a list that was already on its way can't bring them back.
  const removed = useRef(new Set<string>());

  const remove = useCallback((runId: string) => {
    removed.current.add(runId);
    setState((previous) => ({
      ...previous,
      runs: previous.runs?.filter((run) => run.run_id !== runId) ?? null,
    }));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let loaded = false;

    async function poll() {
      try {
        const runs = (await listRuns(controller.signal)).filter(
          (run) => !removed.current.has(run.run_id),
        );
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

  return { ...state, remove };
}
