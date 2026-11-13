import type { Pair } from "@/api/client";

/** What the full-size hazard map opens on: the dashboard's pair, and the panel's choices. */
export interface AssetMapView {
  pair: Pair;
  /** The layer to show first: a flood hazard key or a hazard grid id. Unknown falls back. */
  layer: string | null;
  /** Show the historical map instead of the pair's own. */
  historical: boolean;
}

export const ASSET_MAP_ROUTE = "/runs/:runId/assets/:rowNum/hazard-map";

/** The full-size map's address. The path starts with `runs/`, so it never meets the built `assets/`. */
export function assetMapPath(runId: string, rowNum: number, view: AssetMapView): string {
  const params = new URLSearchParams({ scenario: view.pair.scenario });
  if (view.pair.year !== null) params.set("year", String(view.pair.year));
  if (view.layer) params.set("layer", view.layer);
  if (view.historical) params.set("period", "historical");
  return `/runs/${encodeURIComponent(runId)}/assets/${rowNum}/hazard-map?${params}`;
}

/** Read the view back from a query string, or null if it names no pair. */
export function parseAssetMapView(params: URLSearchParams): AssetMapView | null {
  const scenario = params.get("scenario");
  if (!scenario) return null;
  const yearText = params.get("year");
  let year: number | null = null;
  if (yearText !== null) {
    if (!/^\d+$/.test(yearText)) return null;
    year = Number(yearText);
  }
  return {
    pair: { scenario, year },
    // Links from before hazard grids named a flood map as `hazard`.
    layer: params.get("layer") ?? params.get("hazard"),
    historical: params.get("period") === "historical",
  };
}

/** A row number from the path, or null if it isn't one. */
export function parseRowNum(text: string | undefined): number | null {
  return text !== undefined && /^\d+$/.test(text) ? Number(text) : null;
}
