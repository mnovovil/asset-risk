import { useCallback, useEffect, useRef, useState } from "react";

import type { ReportRequest, ReportStage } from "@/components/report/buildReport";

export type ReportState =
  | { kind: "idle" }
  | { kind: "generating"; stage: ReportStage }
  | { kind: "error"; message: string };

export const STAGE_TEXT: Record<ReportStage, string> = {
  map: "drawing the map",
  charts: "drawing the charts",
  pdf: "writing the PDF",
};

function save(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  // Some browsers read the URL after click returns.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** One report at a time, built off the main bundle, and dropped if the page goes away. */
export function useReport() {
  const [state, setState] = useState<ReportState>({ kind: "idle" });
  const busy = useRef(false);
  const unmounted = useRef(false);

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  const generate = useCallback(async (request: Omit<ReportRequest, "onStage" | "cancelled">) => {
    if (busy.current) return;
    busy.current = true;
    setState({ kind: "generating", stage: "map" });
    try {
      const { buildReport, ReportError } = await import("@/components/report/buildReport");
      try {
        const report = await buildReport({
          ...request,
          onStage: (stage) => !unmounted.current && setState({ kind: "generating", stage }),
          cancelled: () => unmounted.current,
        });
        if (unmounted.current) return;
        save(report.blob, report.fileName);
        setState({ kind: "idle" });
      } catch (error) {
        if (unmounted.current) return;
        const reason =
          error instanceof ReportError ? error.message : "something went wrong. Try again.";
        setState({ kind: "error", message: `Couldn't build the report: ${reason}` });
      }
    } catch {
      if (!unmounted.current) {
        setState({
          kind: "error",
          message: "Couldn't build the report: its code didn't load. Reload the page and try again.",
        });
      }
    } finally {
      busy.current = false;
    }
  }, []);

  return { state, generate };
}
