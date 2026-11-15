import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ASSET_MAP_ROUTE, assetMapPath, parseAssetMapView } from "@/lib/assetMapRoute";
import { AssetMapPage } from "@/pages/AssetMapPage";

import { asset, hazardMapLayers, jsonResponse } from "./helpers";

vi.mock("@/components/dashboard/HazardTileMap", () => ({
  default: ({ tileUrl, label, size }: { tileUrl: string | null; label: string; size: string }) => (
    <p>
      {size} hazard map {tileUrl ?? "with no overlay"}: {label}
    </p>
  ),
}));

const RUN = "run-1";

const DETAIL = {
  ...asset(4, { asset_id: "tower-4", type_source: "assumed" }),
  geometry_wkt: null,
  impacts: [
    {
      scenario: "ssp585",
      year: 2050,
      hazard: "Wind",
      impact_type: "damage",
      aal: 0.01,
      aal_std: null,
      hazard_paths: [],
    },
  ],
  scores: [],
};

function stub(detail: unknown = DETAIL, status = 200) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    requests.push(url);
    if (url.includes("/hazard-maps?")) return jsonResponse(hazardMapLayers(RUN, url));
    if (url === `/api/runs/${RUN}/assets/4`) return jsonResponse(detail, status);
    throw new Error(`Unexpected request: ${url}`);
  });
  return requests;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={ASSET_MAP_ROUTE} element={<AssetMapPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const path = (query: string) => `/runs/${RUN}/assets/4/hazard-map?${query}`;

describe("AssetMapPage", () => {
  beforeEach(() => {
    stub();
  });

  it("shows the asset's map large, with the legend, caveat and a way back", async () => {
    renderAt(path("scenario=ssp585&year=2050"));
    expect(await screen.findByRole("heading", { name: "tower-4 hazard map" })).toBeInTheDocument();
    expect(
      await screen.findByText(/large hazard map .*RiverineInundation.*scenario=ssp585&year=2050/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Flood fixture note: No flood in the data is not proof/)).toBeInTheDocument();
    expect(screen.getByText(/assumed, as Overture has no usable type/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to the portfolio/ })).toHaveAttribute(
      "href",
      `/runs/${RUN}`,
    );
    expect(screen.queryByRole("link", { name: /larger map/ })).not.toBeInTheDocument();
    expect(document.title).toContain("tower-4");
  });

  it("opens on the hazard and period from its address", async () => {
    const requests = stub();
    renderAt(path("scenario=ssp585&year=2050&hazard=CoastalInundation&period=historical"));
    expect(
      await screen.findByText(/hazard map .*CoastalInundation.*\?scenario=historical:/),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Historical" })).toBeChecked();
    expect(requests).toContain(`/api/runs/${RUN}/hazard-maps?scenario=historical`);
  });

  it("opens on wildfire from its address", async () => {
    renderAt(path("scenario=ssp585&year=2050&hazard=Fire"));
    expect(await screen.findByText(/large hazard map .*\/Fire\/.*ssp585/)).toBeInTheDocument();
    expect(screen.getByLabelText("Hazard")).toHaveValue("Fire");
    expect(screen.getByText("Fire fixture note")).toBeInTheDocument();
  });

  it("shows wind's reason for a year it has no map of", async () => {
    renderAt(path("scenario=ssp585&year=2030&hazard=Wind"));
    expect(await screen.findByRole("status")).toHaveTextContent("Wind fixture: 2050 only");
    expect(screen.getByLabelText("Hazard")).toHaveValue("Wind");
    expect(screen.queryByText(/hazard map .*\/Wind\//)).not.toBeInTheDocument();
  });

  it("falls back to the first map for an unknown hazard", async () => {
    renderAt(path("scenario=ssp585&year=2050&hazard=Nope"));
    expect(await screen.findByText(/hazard map .*RiverineInundation/)).toBeInTheDocument();
  });

  it("shows the server's message when the asset can't be loaded", async () => {
    stub({ detail: "The run isn't completed yet." }, 409);
    renderAt(path("scenario=ssp585&year=2050"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The run isn't completed yet.");
  });

  it("says when the asset wasn't assessed, and draws no map", async () => {
    stub({ ...DETAIL, assessable: false, exclusion_reason: "off_land" });
    renderAt(path("scenario=ssp585&year=2050"));
    expect(await screen.findByText(/wasn't assessed/)).toBeInTheDocument();
    expect(screen.queryByText(/hazard map /)).not.toBeInTheDocument();
  });

  it("rejects an incomplete link without calling the API", async () => {
    const requests = stub();
    renderAt(`/runs/${RUN}/assets/4/hazard-map`);
    expect(await screen.findByRole("alert")).toHaveTextContent("incomplete");
    expect(requests).toEqual([]);
  });
});

describe("assetMapPath", () => {
  it("round-trips through the query string", () => {
    const view = { pair: { scenario: "ssp245", year: 2080 }, hazard: "Coastal", historical: true };
    const url = assetMapPath("a/b", 7, view);
    expect(url.startsWith("/runs/a%2Fb/assets/7/hazard-map?")).toBe(true);
    expect(parseAssetMapView(new URLSearchParams(url.split("?")[1]))).toEqual(view);
  });

  it("rejects a year that isn't a number", () => {
    expect(parseAssetMapView(new URLSearchParams("scenario=ssp585&year=soon"))).toBeNull();
  });
});
