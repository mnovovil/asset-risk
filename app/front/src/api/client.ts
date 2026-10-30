import type { components } from "./schema";

export type RunStatus = components["schemas"]["RunStatus"];
export type AppConfig = components["schemas"]["AppConfig"];
export type Summary = components["schemas"]["Summary"];

/** A failed request. `message` is the server's own explanation, written to be shown as is. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // A proxy in front of the API may not answer with JSON.
  }
  const message =
    typeof detail === "string" ? detail : `The server responded with an error (${response.status}).`;
  return new ApiError(response.status, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Can't reach the server. Check that it's running.");
  }
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export const getConfig = (signal?: AbortSignal) => request<AppConfig>("/config", { signal });

export const listRuns = (signal?: AbortSignal) => request<RunStatus[]>("/runs", { signal });

export const getRun = (runId: string, signal?: AbortSignal) =>
  request<RunStatus>(`/runs/${encodeURIComponent(runId)}`, { signal });

export const getSummary = (runId: string, signal?: AbortSignal) =>
  request<Summary>(`/runs/${encodeURIComponent(runId)}/summary`, { signal });

export function createRun(file: File): Promise<RunStatus> {
  const body = new FormData();
  body.append("file", file);
  return request<RunStatus>("/runs", { method: "POST", body });
}

export const exportUrl = (runId: string) => `/api/runs/${encodeURIComponent(runId)}/export.csv`;
