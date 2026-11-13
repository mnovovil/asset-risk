import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssetHazardMap } from "@/components/dashboard/AssetHazardMap";

import { hazardGridResponse, hazardGridWindow, jsonResponse } from "./helpers";

vi.mock("@/components/dashboard/HazardTileMap", () => ({
  default: ({
    overlay,
    label,
  }: {
    overlay: { kind: string; url: string; bounds?: number[] } | null;
    label: string;
  }) => (
    <p>
      Map {overlay?.kind ?? "none"} {overlay?.url ?? ""} {overlay?.bounds?.join(",") ?? ""}: {label}
    </p>
  ),
}));

const dark = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/useColorScheme", () => ({ usePrefersDark: () => dark.value }));

const RUN = "run-1";
const PAIR = { scenario: "ssp585", year: 2050 };

function floodMaps(url: string) {
  const query = url.split("?")[1];
  return ["RiverineInundation", "CoastalInundation"].map((hazard) => ({
    hazard,
    available: true,
    reason: null,
    return_period: 1000,
    units: "m",
    min_value: 0,
    max_value: 2,
    max_zoom: 6,
    legend: ["#fff", "#000"],
    tile_url: `/api/runs/${RUN}/hazard-maps/${hazard}/{z}/{x}/{y}.png?${query}`,
  }));
}

type Override = (url: string) => Response | undefined;

function stub(override: Override = () => undefined) {
  const requests: { url: string; signal?: AbortSignal | null }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    requests.push({ url, signal: init?.signal });
    const custom = override(url);
    if (custom) return custom;
    const grid = hazardGridResponse(url);
    if (grid) return grid;
    if (url.includes("/hazard-maps?")) return jsonResponse(floodMaps(url));
    throw new Error(`Unexpected request: ${url}`);
  });
  return requests;
}

function renderMap(initialLayer: string | null = null) {
  render(
    <AssetHazardMap
      runId={RUN}
      rowNum={1}
      pair={PAIR}
      lat={40.71}
      lon={-73.96}
      hazards={["Wind"]}
      initialLayer={initialLayer}
    />,
  );
}

const pick = async (id: string) =>
  userEvent.selectOptions(await screen.findByLabelText("Layer"), id);

describe("AssetHazardMap with hazard grids", () => {
  beforeEach(() => {
    dark.value = false;
  });

  it("draws a grid's window and states what it is", async () => {
    const requests = stub();
    renderMap();
    await pick("wind_iris_max_speed");
    expect(
      await screen.findByText(
        /Map image .*wind_iris_max_speed\.png\?scenario=ssp585&year=2050&theme=light -75,39\.7,-72\.9,41\.8/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Tropical cyclone wind speed, 1 in 100 years, SSP5-8\.5, 2050/),
    ).toBeInTheDocument();
    expect(screen.getByText(/^19\.2 m\/s/)).toBeInTheDocument();
    expect(screen.getByText(/37\.9 m\/s$/)).toBeInTheDocument();
    expect(screen.getByText("24.4 m/s")).toBeInTheDocument();
    expect(screen.getByText(/Each cell is about 8\.4 × 11 km/)).toBeInTheDocument();
    expect(screen.getByText(/One scale for Historical and SSP5-8\.5, 2050/)).toBeInTheDocument();
    expect(screen.getByText("Feeds the damage figures.")).toBeInTheDocument();
    expect(screen.getByText(/Tropical cyclones only\./)).toBeInTheDocument();
    expect(
      screen.getByText(/Dataset: IRIS\. Source: Sparks & Toumi \(2024\)\./),
    ).toBeInTheDocument();
    expect(requests.map((r) => r.url)).toContain(
      `/api/runs/${RUN}/assets/1/hazard-grids/wind_iris_max_speed?scenario=ssp585&year=2050&theme=light`,
    );
  });

  it("asks for the dark ramp in dark mode", async () => {
    dark.value = true;
    const requests = stub();
    renderMap("heat_jupiter_days_above_35c");
    expect(await screen.findByText(/Map image .*theme=dark/)).toBeInTheDocument();
    expect(screen.getByText("Indicator only, not in the damage figures.")).toBeInTheDocument();
    expect(
      requests.some((r) =>
        r.url.endsWith("heat_jupiter_days_above_35c?scenario=ssp585&year=2050&theme=dark"),
      ),
    ).toBe(true);
  });

  it("replaces the map with a notice when the dataset lacks the pair", async () => {
    const requests = stub();
    renderMap("subsidence_csm_rate");
    expect(
      await screen.findByText(
        "No data for this scenario/year: This dataset has no ssp585 scenario.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Map /)).not.toBeInTheDocument();
    expect(screen.queryByText(/This asset's cell/)).not.toBeInTheDocument();
    expect(requests.some((r) => r.url.includes("/hazard-grids/subsidence"))).toBe(false);
  });

  it("replaces the map with the window's reason when there's nothing to draw", async () => {
    stub((url) =>
      url.includes("/hazard-grids/wind_iris_max_speed?")
        ? jsonResponse({
            ...hazardGridWindow(url),
            available: false,
            reason: "This dataset doesn't cover this point",
            bounds: null,
            image_url: null,
          })
        : undefined,
    );
    renderMap("wind_iris_max_speed");
    expect(await screen.findByText("This dataset doesn't cover this point.")).toBeInTheDocument();
    expect(screen.queryByText(/^Map /)).not.toBeInTheDocument();
  });

  it("shows a cell with no data as hollow, never as a low colour", async () => {
    stub();
    render(
      <AssetHazardMap
        runId={RUN}
        rowNum={1}
        pair={{ scenario: "historical", year: null }}
        lat={40.71}
        lon={-73.96}
        hazards={[]}
        initialLayer="subsidence_csm_rate"
      />,
    );
    expect(await screen.findByText(/No data at this point/)).toBeInTheDocument();
    expect(screen.getByText(/No data at this point/).querySelector(".dot-hollow")).not.toBeNull();
    expect(screen.queryByText(/This asset's cell/)).not.toBeInTheDocument();
    expect(screen.getByText(/The asset's cell: no data at this point/)).toBeInTheDocument();
    expect(screen.queryByText(/One scale for Historical/)).not.toBeInTheDocument();
  });

  it("shows a failed read's own message", async () => {
    stub((url) =>
      url.includes("/hazard-grids/wind_iris_max_speed?")
        ? jsonResponse({ detail: "Could not read this hazard grid: S3 down" }, 502)
        : undefined,
    );
    renderMap("wind_iris_max_speed");
    expect(await screen.findByText("Could not read this hazard grid: S3 down")).toBeInTheDocument();
  });

  it("still shows the flood maps when the grid list fails", async () => {
    stub((url) =>
      url.includes("/hazard-grids?") ? jsonResponse({ detail: "boom" }, 500) : undefined,
    );
    renderMap();
    expect(await screen.findByText(/Map tiles .*RiverineInundation/)).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("refetches both lists and the window for Historical, and keeps the layer", async () => {
    const requests = stub();
    renderMap("wind_iris_max_speed");
    await screen.findByText(/Map image .*scenario=ssp585/);
    await userEvent.click(screen.getByRole("radio", { name: "Historical" }));
    expect(
      await screen.findByText(
        /Map image .*wind_iris_max_speed\.png\?scenario=historical&theme=light/,
      ),
    ).toBeInTheDocument();
    const urls = requests.map((r) => r.url);
    expect(urls).toContain(`/api/runs/${RUN}/hazard-maps?scenario=historical`);
    expect(urls).toContain(`/api/runs/${RUN}/assets/1/hazard-grids?scenario=historical`);
    expect(screen.getByLabelText("Layer")).toHaveValue("wind_iris_max_speed");
    expect(screen.queryByText(/One scale for Historical/)).not.toBeInTheDocument();
  });

  it("drops a window that's still loading when another layer is picked", async () => {
    let release: () => void = () => undefined;
    const slow = new Promise<void>((resolve) => {
      release = resolve;
    });
    const requests = stub();
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      requests.push({ url, signal: init?.signal });
      if (url.includes("/hazard-grids/wind_iris_max_speed?")) await slow;
      const grid = hazardGridResponse(url);
      if (grid) return grid;
      return jsonResponse(floodMaps(url));
    });
    renderMap("wind_iris_max_speed");
    await waitFor(() =>
      expect(requests.some((r) => r.url.includes("/hazard-grids/wind_iris_max_speed?"))).toBe(true),
    );
    await pick("heat_jupiter_days_above_35c");
    expect(await screen.findByText(/Map image .*heat_jupiter_days_above_35c/)).toBeInTheDocument();
    const windRequest = requests.find((r) => r.url.includes("/hazard-grids/wind_iris_max_speed?"));
    expect(windRequest?.signal?.aborted).toBe(true);
    release();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText(/Map image .*heat_jupiter_days_above_35c/)).toBeInTheDocument();
  });
});
