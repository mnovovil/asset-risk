import type { RunStatus } from "@/api/client";

export function runStatus(overrides: Partial<RunStatus> = {}): RunStatus {
  return {
    run_id: "11111111-1111-4111-8111-111111111111",
    source_name: "portfolio.csv",
    total_rows: 3,
    status: "queued",
    stage: null,
    done: 0,
    total: 0,
    error: null,
    created_at: "2026-10-30T12:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
    queue_position: null,
    ...overrides,
  };
}

export const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

type Handler = (init?: RequestInit) => Response | Promise<Response>;

/** Answer fetch by "METHOD /path". An unexpected request fails the test. */
export function fakeFetch(routes: Record<string, Handler>) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    const handler = routes[key];
    if (!handler) throw new Error(`Unexpected request: ${key}`);
    return handler(init);
  };
}

export const CONFIG = {
  scenarios: ["ssp585"],
  years: [2050],
  default_building_type: "Buildings/Commercial",
  max_portfolio_rows: 3,
  max_upload_mb: 1,
};
