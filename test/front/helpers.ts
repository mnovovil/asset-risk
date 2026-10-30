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

export const SUMMARY = {
  total_assets: 3,
  assessable: 2,
  excluded: 1,
  assumed_type: 1,
  global_curve: 0,
  nearest_match: 1,
  no_building: 0,
  failed_assets: 0,
  exclusions: [{ reason: "off_land", assets: 1 }],
  shared_hazards: ["Wind"],
};

export const asset = (row_num: number, overrides: object = {}) => ({
  row_num,
  asset_id: `asset-${row_num}`,
  lat: 40,
  lon: -3,
  match_type: "intersects",
  distance_m: 0,
  building_id: "b",
  name: null,
  class: "office",
  subtype: "commercial",
  height: null,
  num_floors: null,
  region: "Europe",
  region_source: "contains",
  physrisk_type: "Buildings/Commercial",
  physrisk_location: "Europe",
  location_fallback: false,
  type_source: "class",
  assessable: true,
  exclusion_reason: null,
  ...overrides,
});

export const ASSETS = [
  asset(1),
  asset(2, { type_source: "assumed", class: null, subtype: null }),
  asset(3, { assessable: false, exclusion_reason: "off_land", match_type: "none" }),
];

export const TRAJECTORY = [
  { scenario: "historical", year: null, assets: 2, mean_total_aal: 0.003, mean_shared_aal: 0.002, hazards: 2 },
  { scenario: "ssp245", year: 2050, assets: 2, mean_total_aal: 0.006, mean_shared_aal: 0.006, hazards: 1 },
  { scenario: "ssp370", year: 2050, assets: 0, mean_total_aal: null, mean_shared_aal: null, hazards: 0 },
  { scenario: "ssp585", year: 2030, assets: 2, mean_total_aal: 0.01, mean_shared_aal: 0.004, hazards: 2 },
  { scenario: "ssp585", year: 2050, assets: 2, mean_total_aal: 0.02, mean_shared_aal: 0.005, hazards: 2 },
];

export const COVERAGE = [
  { scenario: "ssp245", year: 2050, hazard: "Fire", assets: 0, covered: false, shared: false },
  { scenario: "ssp245", year: 2050, hazard: "Wind", assets: 2, covered: true, shared: true },
  { scenario: "ssp585", year: 2050, hazard: "Fire", assets: 2, covered: true, shared: false },
  { scenario: "ssp585", year: 2050, hazard: "Wind", assets: 2, covered: true, shared: true },
];

const impact = (row_num: number, hazard: string, aal: number) => ({
  row_num,
  asset_id: `asset-${row_num}`,
  lat: 40,
  lon: -3,
  hazard,
  impact_type: "damage",
  aal,
  aal_std: null,
});

const score = (row_num: number, hazard: string, value: number, label: string | null) => ({
  row_num,
  asset_id: `asset-${row_num}`,
  hazard,
  score: value,
  label,
});

const total = (row_num: number, total_aal: number, shared_aal: number, hazards: number) => ({
  row_num,
  asset_id: `asset-${row_num}`,
  total_aal,
  shared_aal,
  hazards,
});

/** Results that differ by scenario, as the real ones do: ssp245 has no fire. */
const PAIRS: Record<string, { totals: unknown[]; impacts: unknown[]; scores: unknown[] }> = {
  "scenario=historical": {
    totals: [],
    scores: [],
    impacts: [
      impact(1, "Wind", 0.001),
      impact(1, "Fire", 0.001),
      impact(2, "Wind", 0.003),
      impact(2, "Fire", 0.001),
    ],
  },
  "scenario=ssp585&year=2050": {
    totals: [total(1, 0.012, 0.002, 2), total(2, 0.028, 0.008, 2)],
    impacts: [
      impact(1, "Wind", 0.002),
      impact(1, "Fire", 0.01),
      impact(2, "Wind", 0.008),
      impact(2, "Fire", 0.02),
    ],
    scores: [
      score(1, "Wind", 1, "Low impact"),
      score(1, "Fire", 3, "High impact"),
      score(1, "ChronicHeat", -1, "No vulnerability"),
      score(1, "PluvialInundation", -2, "No hazard data"),
      score(2, "Wind", -2, "No hazard data"),
      score(2, "Fire", 0, "Very low impact"),
      score(2, "ChronicHeat", -1, "No vulnerability"),
      score(2, "PluvialInundation", -2, "No hazard data"),
    ],
  },
  "scenario=ssp245&year=2050": {
    totals: [total(1, 0.004, 0.004, 1), total(2, 0.008, 0.008, 1)],
    impacts: [impact(1, "Wind", 0.004), impact(2, "Wind", 0.008)],
    scores: [score(1, "Wind", 2, "Medium impact"), score(2, "Wind", 2, "Medium impact")],
  },
};

const ENDPOINTS: Record<string, unknown> = {
  summary: SUMMARY,
  assets: ASSETS,
  trajectory: TRAJECTORY,
  coverage: COVERAGE,
};

/** Answer a results request from the fixtures above. */
export function resultsResponse(url: string): Response {
  if (url === "/api/config") return jsonResponse(CONFIG);
  const [path, query] = url.split("?");
  const endpoint = path.split("/").pop() as string;
  if (endpoint === "impacts" || endpoint === "totals" || endpoint === "scores") {
    const pair = PAIRS[query];
    if (!pair) throw new Error(`No fixture for ${url}`);
    return jsonResponse(pair[endpoint]);
  }
  if (endpoint in ENDPOINTS) return jsonResponse(ENDPOINTS[endpoint]);
  throw new Error(`Unexpected request: ${url}`);
}
