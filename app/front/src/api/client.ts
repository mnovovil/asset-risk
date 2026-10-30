import type { components } from "./schema";

export type RunStatus = components["schemas"]["RunStatus"];
export type AppConfig = components["schemas"]["AppConfig"];
export type Summary = components["schemas"]["Summary"];
export type Asset = components["schemas"]["Asset"];
export type AssetDetail = components["schemas"]["AssetDetail"];
export type AssetTotal = components["schemas"]["AssetTotal"];
export type Coverage = components["schemas"]["Coverage"];
export type HazardCurve = components["schemas"]["HazardCurve"];
export type Impact = components["schemas"]["Impact"];
export type Score = components["schemas"]["Score"];
export type TrajectoryPoint = components["schemas"]["TrajectoryPoint"];

/** A scenario and year that were assessed. The historical baseline has year null. */
export interface Pair {
  scenario: string;
  year: number | null;
}

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

const runPath = (runId: string) => `/runs/${encodeURIComponent(runId)}`;

function pairQuery({ scenario, year }: Pair): string {
  const params = new URLSearchParams({ scenario });
  if (year !== null) params.set("year", String(year));
  return params.toString();
}

export const getAssets = (runId: string, signal?: AbortSignal) =>
  request<Asset[]>(`${runPath(runId)}/assets`, { signal });

export const getAsset = (runId: string, rowNum: number, signal?: AbortSignal) =>
  request<AssetDetail>(`${runPath(runId)}/assets/${rowNum}`, { signal });

export const getTrajectory = (runId: string, signal?: AbortSignal) =>
  request<TrajectoryPoint[]>(`${runPath(runId)}/trajectory`, { signal });

export const getCoverage = (runId: string, signal?: AbortSignal) =>
  request<Coverage[]>(`${runPath(runId)}/coverage`, { signal });

export const getImpacts = (runId: string, pair: Pair, signal?: AbortSignal) =>
  request<Impact[]>(`${runPath(runId)}/impacts?${pairQuery(pair)}`, { signal });

export const getTotals = (runId: string, pair: Pair, signal?: AbortSignal) =>
  request<AssetTotal[]>(`${runPath(runId)}/totals?${pairQuery(pair)}`, { signal });

export const getScores = (runId: string, pair: Pair, signal?: AbortSignal) =>
  request<Score[]>(`${runPath(runId)}/scores?${pairQuery(pair)}`, { signal });

export const getHazardCurve = (runId: string, rowNum: number, pair: Pair, signal?: AbortSignal) =>
  request<HazardCurve>(`${runPath(runId)}/assets/${rowNum}/hazard-curve?${pairQuery(pair)}`, {
    signal,
  });

export const exportUrl = (runId: string) => `/api/runs/${encodeURIComponent(runId)}/export.csv`;
