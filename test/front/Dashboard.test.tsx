import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { forgetFloodZoneDefinitions } from "@/lib/floodZones";

import { asset, jsonResponse, resultsResponse, SUMMARY, TRAJECTORY } from "./helpers";

vi.mock("@/components/dashboard/RiskMap", () => ({
  default: ({
    colorBy,
    assets,
    clusters,
  }: {
    colorBy: string;
    assets: unknown[];
    clusters: unknown[];
  }) => (
    <p>
      Map of {assets.length} assets in {clusters.length} clusters by {colorBy}
    </p>
  ),
}));

vi.mock("@/components/dashboard/HazardTileMap", () => ({
  default: ({ tileUrl, label }: { tileUrl: string | null; label: string }) => (
    <p>
      Hazard map {tileUrl ?? "with no overlay"}: {label}
    </p>
  ),
}));

const RUN = "run-1";

/** What the API lists: the two public flood maps, with no map for ssp370. */
function hazardMaps(url: string) {
  const query = url.split("?")[1];
  const missing = query.includes("ssp370");
  return ["RiverineInundation", "CoastalInundation"].map((hazard) => ({
    hazard,
    available: !missing,
    reason: missing ? "physrisk has no flood map for this scenario" : null,
    return_period: 1000,
    units: "m",
    min_value: 0,
    max_value: 2,
    max_zoom: 6,
    legend: ["rgba(237, 176, 129, 0.78)", "rgba(75, 35, 98, 0.78)"],
    tile_url: missing ? null : `/api/runs/${RUN}/hazard-maps/${hazard}/{z}/{x}/{y}.png?${query}`,
  }));
}

function stub(overrides: Record<string, unknown> = {}) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    requests.push(url);
    if (url.includes("/hazard-maps?")) return jsonResponse(hazardMaps(url));
    if (/\/assets\/\d+$/.test(url)) {
      return jsonResponse(overrides.detail);
    }
    const endpoint = url.split("?")[0].split("/").pop() as string;
    if (endpoint in overrides) return jsonResponse(overrides[endpoint]);
    return resultsResponse(url);
  });
  return requests;
}

async function renderDashboard() {
  render(<Dashboard runId={RUN} />);
  // The first test in the file pays for loading the dashboard and its charts, which took up to
  // 1.8 s against Testing Library's default of 1 s and failed about one run in ten.
  return screen.findByRole("heading", { name: "Risk by asset and hazard" }, { timeout: 5000 });
}

const meanLoss = () =>
  within(screen.getByText("Mean annual loss, equal-weighted").parentElement as HTMLElement);
const scoreTable = () => within(screen.getByRole("region", { name: "Risk by asset and hazard" }));

const rowFor = (name: string) => screen.getByRole("button", { name }).closest("tr") as HTMLElement;

describe("Dashboard", () => {
  beforeEach(() => {
    forgetFloodZoneDefinitions();
    stub();
  });

  it("starts on the fullest scenario and shows headline figures", async () => {
    await renderDashboard();
    expect(screen.getByLabelText("Scenario")).toHaveValue("ssp585");
    expect(screen.getByLabelText("Year")).toHaveValue("2050");
    expect(screen.getByText("Mean annual loss, equal-weighted")).toBeInTheDocument();
    expect(meanLoss().getByText("2.000%")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument(); // assumed type
  });

  describe("today's baseline", () => {
    async function selectBaseline() {
      const requests = stub();
      await renderDashboard();
      await userEvent.selectOptions(screen.getByLabelText("Scenario"), "Today (baseline)");
      await screen.findByText(/physrisk scores scenarios only/);
      return requests;
    }

    it("is offered first, and loads results with no year", async () => {
      const requests = await selectBaseline();
      const options = within(screen.getByLabelText("Scenario")).getAllByRole("option");
      expect(options[0]).toHaveTextContent("Today (baseline)");
      expect(screen.getByLabelText("Year")).toBeDisabled();
      expect(requests).toContain(`/api/runs/${RUN}/totals?scenario=historical`);
    });

    it("shows annual loss without scores, and nothing compared with itself", async () => {
      await selectBaseline();
      expect(screen.getByText("Map of 3 assets in 0 clusters by total")).toBeInTheDocument();
      const colourBy = within(screen.getByLabelText("Colour the map by")).getAllByRole("option");
      expect(colourBy.map((o) => o.textContent)).toEqual(["Total annual loss"]);
      expect(screen.getByText(/present-day baseline, which it treats as 2025/)).toBeInTheDocument();
      expect(screen.queryByText(/Diamonds show/)).not.toBeInTheDocument();
      expect(scoreTable().queryByText("Not returned")).not.toBeInTheDocument();
      expect(scoreTable().getByRole("columnheader", { name: "Wildfire" })).toBeInTheDocument();
    });

    it("goes back to a scenario at its preferred year", async () => {
      await selectBaseline();
      await userEvent.selectOptions(screen.getByLabelText("Scenario"), "ssp585");
      expect(screen.getByLabelText("Year")).toHaveValue("2050");
      expect(await screen.findByText(/Diamonds show/)).toBeInTheDocument();
    });
  });

  it("doesn't offer a year with no results", async () => {
    const empty = { ...TRAJECTORY[3], year: 2025, assets: 0, mean_total_aal: null, mean_shared_aal: null };
    stub({ trajectory: [...TRAJECTORY, empty] });
    await renderDashboard();
    const years = within(screen.getByLabelText("Year")).getAllByRole("option").map((o) => o.textContent);
    expect(years).toEqual(["2030", "2050"]);
  });

  it("gives the map the run's clusters", async () => {
    const cluster = {
      cluster_id: 0,
      assets: 2,
      row_nums: [1, 2],
      lat: 40,
      lon: -3,
      bounds: [-3, 40, -3, 40],
    };
    stub({ clusters: [cluster] });
    await renderDashboard();
    expect(await screen.findByText("Map of 3 assets in 1 clusters by total")).toBeInTheDocument();
  });

  it("still shows every asset when the clusters can't be loaded", async () => {
    vi.stubGlobal("fetch", async (url: string) =>
      url.endsWith("/clusters") ? jsonResponse({ detail: "boom" }, 500) : resultsResponse(url),
    );
    await renderDashboard();
    expect(await screen.findByText("Map of 3 assets in 0 clusters by total")).toBeInTheDocument();
  });

  it("compares history over the same hazards, not all of them", async () => {
    await renderDashboard();
    await userEvent.selectOptions(screen.getByLabelText("Scenario"), "ssp245");
    // Wind only: (0.1% + 0.3%) / 2, not the 0.3% mean that would include fire.
    await waitFor(() => expect(screen.getByText(/same hazards: 0\.200%/)).toBeInTheDocument());
  });

  it("changes everything when the scenario changes, and says what's missing", async () => {
    await renderDashboard();
    expect(screen.getByRole("columnheader", { name: "Wildfire" })).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Scenario"), "ssp245");
    await waitFor(() =>
      expect(screen.queryByRole("columnheader", { name: "Wildfire" })).not.toBeInTheDocument(),
    );
    expect(meanLoss().getByText("0.600%")).toBeInTheDocument();
    expect(screen.getByText(/Wildfire has no data for this scenario/)).toBeInTheDocument();
    expect(screen.getByText(/Not available for this scenario: Wildfire/)).toBeInTheDocument();
  });

  it("marks a scenario with no results and explains choosing it", async () => {
    await renderDashboard();
    expect(screen.getByRole("option", { name: "SSP3-7.0 (no data)" })).toBeInTheDocument();
    expect(screen.getByText(/No results at all for SSP3-7.0/)).toBeInTheDocument();
  });

  it("keeps a year that exists in the new scenario, or moves to one that does", async () => {
    await renderDashboard();
    await userEvent.selectOptions(screen.getByLabelText("Year"), "2030");
    const requests = stub({ totals: [], impacts: [], scores: [] });
    await userEvent.selectOptions(screen.getByLabelText("Scenario"), "ssp245");
    expect(screen.getByLabelText("Year")).toHaveValue("2050");
    await waitFor(() => expect(requests.some((r) => r.includes("ssp245&year=2050"))).toBe(true));
  });

  it("keeps no data and no model apart from a low score", async () => {
    await renderDashboard();
    const assetTwo = rowFor("asset-2");
    expect(within(assetTwo).getByText("0.800%")).toBeInTheDocument(); // wind: a loss, but no score
    const assetOne = rowFor("asset-1");
    expect(within(assetOne).getByText("Low impact")).toBeInTheDocument();
    expect(screen.getByText(/No damage model for this building type: Chronic heat/)).toBeInTheDocument();
    expect(screen.getByText(/No hazard data at these locations: Surface water flood/)).toBeInTheDocument();
  });

  it("sorts by total, then by a chosen column in either direction", async () => {
    await renderDashboard();
    const names = () =>
      scoreTable()
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent);
    expect(names()).toEqual(["asset-2", "asset-1"]);

    await userEvent.click(screen.getByRole("button", { name: /^Wildfire/ }));
    expect(screen.getByRole("columnheader", { name: /Wildfire/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(names()).toEqual(["asset-1", "asset-2"]);
    await userEvent.click(screen.getByRole("button", { name: /^Wildfire/ }));
    expect(names()).toEqual(["asset-2", "asset-1"]);
  });

  it("recolours the map from the filter row", async () => {
    await renderDashboard();
    expect(screen.getByText("Map of 3 assets in 0 clusters by total")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Colour the map by"), "Fire");
    expect(screen.getByText("Map of 3 assets in 0 clusters by Fire")).toBeInTheDocument();
  });

  it("warns when most building types are assumed", async () => {
    stub({ summary: { ...SUMMARY, assumed_type: 2 } });
    await renderDashboard();
    expect(screen.getByText(/assumed for 100% of assets, using Buildings\/Commercial/)).toBeInTheDocument();
  });

  it("lists excluded assets with the reason", async () => {
    await renderDashboard();
    expect(screen.getByText(/1 excluded: Off land/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "asset-3" })).toBeInTheDocument();
  });

  it("states the model's limits next to the numbers", async () => {
    await renderDashboard();
    expect(screen.getByText(/single climate model\./)).toBeInTheDocument();
    expect(screen.getByText(/not for decisions about one site/)).toBeInTheDocument();
  });

  it("explains a portfolio with nothing assessed", async () => {
    stub({
      summary: {
        ...SUMMARY,
        assessable: 0,
        excluded: 3,
        assumed_type: 0,
        nearest_match: 0,
        exclusions: [{ reason: "invalid", assets: 3 }],
        shared_hazards: [],
      },
      trajectory: TRAJECTORY.map((p) => ({ ...p, assets: 0, hazards: 0 })),
      coverage: [],
      totals: [],
      impacts: [],
      scores: [],
    });
    render(<Dashboard runId={RUN} />);
    expect(await screen.findByText(/No asset in this portfolio could be assessed/)).toBeInTheDocument();
    expect(screen.getByText("0 of 3")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Risk by asset and hazard" })).not.toBeInTheDocument();
  });

  it("works with a single asset", async () => {
    stub({
      summary: { ...SUMMARY, total_assets: 1, assessable: 1, excluded: 0, exclusions: [] },
      assets: [asset(1)],
      totals: [{ row_num: 1, asset_id: "only", total_aal: 0.01, shared_aal: 0.01, hazards: 1 }],
      impacts: [],
      scores: [],
    });
    await renderDashboard();
    expect(screen.getByRole("button", { name: "only" })).toBeInTheDocument();
  });

  it("pages through a large portfolio without drawing every row", async () => {
    const size = 5000;
    const ids = Array.from({ length: size }, (_, i) => i + 1);
    stub({
      summary: { ...SUMMARY, total_assets: size, assessable: size, excluded: 0, exclusions: [] },
      assets: ids.map((id) => asset(id)),
      totals: ids.map((id) => ({
        row_num: id,
        asset_id: `asset-${id}`,
        total_aal: id / 100000,
        shared_aal: id / 100000,
        hazards: 1,
      })),
      impacts: [],
      scores: [],
    });
    await renderDashboard();
    expect(scoreTable().getAllByRole("rowheader")).toHaveLength(25);
    expect(screen.getByText("Page 1 of 200")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "asset-5000" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 200")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "asset-4975" })).toBeInTheDocument();
    expect(screen.getByText(/The 15 highest of 5000/)).toBeInTheDocument();
  });

  it("renders ids as text, and copes with very long ones", async () => {
    const hostile = `<img src=x onerror=alert(1)>${"x".repeat(300)}`;
    stub({
      totals: [{ row_num: 1, asset_id: hostile, total_aal: 0.01, shared_aal: 0.01, hazards: 1 }],
      impacts: [],
      scores: [],
    });
    await renderDashboard();
    expect(screen.getByRole("button", { name: hostile })).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("explains results that can't load", async () => {
    vi.stubGlobal("fetch", async (url: string) =>
      url.endsWith("/summary")
        ? jsonResponse({ detail: "This run has no results: it is failed" }, 409)
        : resultsResponse(url),
    );
    render(<Dashboard runId={RUN} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This run has no results");
  });

  describe("the asset panel", () => {
    const detail = {
      ...asset(1, {
        name: "Tower",
        height: 30,
        num_floors: 8,
        type_source: "assumed",
        location_fallback: true,
        physrisk_location: "Global",
        region: "Africa",
      }),
      geometry_wkt: null,
      impacts: [
        {
          scenario: "ssp585",
          year: 2050,
          hazard: "Wind",
          impact_type: "damage",
          aal: 0.002,
          aal_std: null,
          hazard_paths: [],
        },
        {
          scenario: "ssp245",
          year: 2050,
          hazard: "Wind",
          impact_type: "damage",
          aal: 0.9,
          aal_std: null,
          hazard_paths: [],
        },
        {
          scenario: "historical",
          year: null,
          hazard: "Wind",
          impact_type: "damage",
          aal: 0.0042,
          aal_std: null,
          hazard_paths: [],
        },
      ],
      scores: [
        { scenario: "ssp585", year: 2050, hazard: "Wind", score: 1, label: "Low impact" },
        { scenario: "ssp585", year: 2050, hazard: "ChronicHeat", score: -1, label: "No vulnerability" },
      ],
    };

    async function openPanel() {
      stub({ detail });
      await renderDashboard();
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      return screen.findByRole("dialog", { name: "Asset details" });
    }

    it("shows the building, how it was modelled, and only the selected scenario", async () => {
      const panel = within(await openPanel());
      expect(await panel.findByText("Tower")).toBeInTheDocument();
      expect(panel.getByText(/They don't affect the results/)).toBeInTheDocument();
      expect(panel.getByText(/Assumed: Overture has no usable type/)).toBeInTheDocument();
      expect(panel.getByText(/no Africa model for this type/)).toBeInTheDocument();
      const results = within(
        panel.getByRole("columnheader", { name: "Annual loss" }).closest("table") as HTMLElement,
      );
      expect(results.getByText("0.200%")).toBeInTheDocument();
      expect(results.queryByText("90.000%")).not.toBeInTheDocument();
      expect(results.getByText("No model")).toBeInTheDocument();
    });

    describe("its chart over time", () => {
      const chartTable = (panel: ReturnType<typeof within>) =>
        within(panel.getByText("Show as a table").closest("details") as HTMLElement);

      it("offers each hazard's loss, then each hazard's score", async () => {
        const panel = within(await openPanel());
        const select = await panel.findByLabelText("Chart");
        expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
          "Annual loss — Tropical cyclone wind",
          "Score — Tropical cyclone wind",
          "Score — Chronic heat",
        ]);
      });

      it("draws every scenario's loss with the baseline, and no hazard curve", async () => {
        const requests = stub({ detail });
        await renderDashboard();
        await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
        const panel = within(await screen.findByRole("dialog"));
        expect(
          await panel.findByRole("img", { name: /tropical cyclone wind annual loss by year/ }),
        ).toBeInTheDocument();
        const table = chartTable(panel);
        expect(table.getByRole("columnheader", { name: "Today (baseline)" })).toBeInTheDocument();
        expect(table.getByText("90.000%")).toBeInTheDocument();
        expect(table.getByText("0.200%")).toBeInTheDocument();
        expect(table.getByText("0.420%")).toBeInTheDocument();
        expect(panel.getByText("No tropical cyclone wind loss results for SSP3-7.0.")).toBeInTheDocument();
        expect(requests.some((r) => r.includes("hazard-curve"))).toBe(false);
      });

      it("switches to a score, with no baseline", async () => {
        const panel = within(await openPanel());
        await userEvent.selectOptions(await panel.findByLabelText("Chart"), "score:Wind");
        expect(panel.getByRole("img", { name: /tropical cyclone wind score by year/ })).toBeInTheDocument();
        const table = chartTable(panel);
        expect(table.getByRole("cell", { name: "Low" })).toBeInTheDocument();
        expect(table.queryByRole("columnheader", { name: "Today (baseline)" })).not.toBeInTheDocument();
        expect(panel.getByText(/No tropical cyclone wind score results for SSP2-4.5 and SSP3-7.0/))
          .toBeInTheDocument();
        expect(panel.getByText(/A low score isn't proof of low risk/)).toBeInTheDocument();
      });

      it("lists a score with no model as a note, not a point", async () => {
        const panel = within(await openPanel());
        await userEvent.selectOptions(await panel.findByLabelText("Chart"), "score:ChronicHeat");
        expect(panel.getByText(/Not scored: SSP5-8.5, 2050 \(No model\)/)).toBeInTheDocument();
        expect(panel.queryByText("Show as a table")).not.toBeInTheDocument();
        expect(panel.getByText("No scenario results for chronic heat.")).toBeInTheDocument();
      });
    });

    it("shows hazard maps under the river flood table", async () => {
      const panel = within(await openPanel());
      const heading = await panel.findByRole("heading", { name: "Hazard maps" });
      const table = panel.getByText("Show as a table");
      expect(table.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(await panel.findByText(/Hazard map .*RiverineInundation.*scenario=ssp585&year=2050/))
        .toBeInTheDocument();
      expect(panel.getByText(/No flood in the data$/)).toBeInTheDocument();
    });

    it("lists hazards with no public map, but won't select them", async () => {
      const panel = within(await openPanel());
      const select = await panel.findByLabelText("Hazard");
      const options = within(select).getAllByRole("option") as HTMLOptionElement[];
      expect(options.map((o) => [o.textContent, o.disabled])).toEqual([
        ["River flood", false],
        ["Coastal flood", false],
        ["Tropical cyclone wind (no public map)", true],
        ["Chronic heat (no public map)", true],
      ]);
    });

    it("switches the layer and the period", async () => {
      const requests = stub({ detail });
      await renderDashboard();
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      const panel = within(await screen.findByRole("dialog"));
      await userEvent.selectOptions(await panel.findByLabelText("Hazard"), "CoastalInundation");
      expect(panel.getByText(/Hazard map .*CoastalInundation.*ssp585/)).toBeInTheDocument();

      await userEvent.click(panel.getByRole("radio", { name: "Historical" }));
      expect(
        await panel.findByText(/Hazard map .*CoastalInundation.*\?scenario=historical:.*Historical/),
      ).toBeInTheDocument();
      expect(requests.some((r) => r.endsWith("/hazard-maps?scenario=historical"))).toBe(true);
    });

    it("links to a larger map in a new tab, on the same hazard and period", async () => {
      stub({ detail });
      await renderDashboard();
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      const panel = within(await screen.findByRole("dialog"));
      const link = await panel.findByRole("link", { name: "Open a larger map in a new tab" });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")).toContain("noopener");
      const base = `/runs/${RUN}/assets/1/hazard-map?scenario=ssp585&year=2050`;
      expect(link).toHaveAttribute("href", `${base}&hazard=RiverineInundation`);

      await userEvent.selectOptions(panel.getByLabelText("Hazard"), "CoastalInundation");
      expect(link).toHaveAttribute("href", `${base}&hazard=CoastalInundation`);
      await userEvent.click(panel.getByRole("radio", { name: "Historical" }));
      await panel.findByText(/Hazard map .*\?scenario=historical/);
      expect(panel.getByRole("link", { name: /larger map/ })).toHaveAttribute(
        "href",
        `${base}&hazard=CoastalInundation&period=historical`,
      );
    });

    it("links the baseline's larger map with no year", async () => {
      stub({ detail });
      await renderDashboard();
      await userEvent.selectOptions(screen.getByLabelText("Scenario"), "Today (baseline)");
      await screen.findByText(/physrisk scores scenarios only/);
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      const panel = within(await screen.findByRole("dialog"));
      expect(await panel.findByRole("link", { name: /larger map/ })).toHaveAttribute(
        "href",
        `/runs/${RUN}/assets/1/hazard-map?scenario=historical&hazard=RiverineInundation`,
      );
    });

    it("says why a scenario has no map", async () => {
      stub({ detail });
      await renderDashboard();
      await userEvent.selectOptions(screen.getByLabelText("Scenario"), "ssp370");
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      const panel = within(await screen.findByRole("dialog"));
      expect(await panel.findByText("physrisk has no flood map for this scenario.")).toBeInTheDocument();
      expect(panel.getByText(/Hazard map with no overlay/)).toBeInTheDocument();
    });

    it("shows the baseline on its own, with no scores", async () => {
      stub({ detail });
      await renderDashboard();
      await userEvent.selectOptions(screen.getByLabelText("Scenario"), "Today (baseline)");
      await screen.findByText(/physrisk scores scenarios only/);
      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      const panel = within(await screen.findByRole("dialog", { name: "Asset details" }));
      expect(await panel.findByRole("heading", { name: "Results for Today (baseline)" })).toBeInTheDocument();
      expect(panel.getAllByText("0.420%").length).toBeGreaterThan(0);
      expect(panel.queryByRole("columnheader", { name: "Score" })).not.toBeInTheDocument();
      // The chart still shows every scenario, with nothing marked as selected.
      expect(panel.getByRole("img", { name: /annual loss by year/ })).toBeInTheDocument();
      expect(panel.queryByText(/dashed vertical line marks/)).not.toBeInTheDocument();
    });

    it("closes with the button and with Escape", async () => {
      await openPanel();
      await userEvent.click(screen.getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
      await screen.findByRole("dialog");
      await userEvent.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("moves focus into the panel", async () => {
      await openPanel();
      expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    });

    describe("its FEMA flood zone", () => {
      async function openWith(fema: object, { definitionsFail = false } = {}) {
        stub({ detail: { ...detail, fema_map_as_of: "2026-11-13", ...fema } });
        if (definitionsFail) {
          const answer = globalThis.fetch;
          vi.stubGlobal("fetch", async (url: string) =>
            url === "/api/flood-zone-definitions"
              ? jsonResponse({ detail: "Definitions are down" }, 500)
              : answer(url),
          );
        }
        await renderDashboard();
        await userEvent.click(screen.getByRole("button", { name: "asset-1" }));
        const panel = await screen.findByRole("dialog", { name: "Asset details" });
        await within(panel).findByRole("heading", { name: "FEMA flood zone" });
        return within(panel);
      }

      const mappedAE = {
        fema_status: "mapped",
        fema_zone: "AE",
        fema_zone_key: "AE",
        in_sfha: true,
        base_flood_elevation: 8,
        base_flood_elevation_unit: "feet",
        base_flood_elevation_datum: "NGVD29",
        fema_dfirm_id: "12086C",
        fema_matches: 1,
      };

      it("shows the zone, what it means, and where that comes from", async () => {
        const panel = await openWith(mappedAE);
        const term = (name: string) => panel.getByText(name, { selector: "dt" }).nextElementSibling;
        expect(await panel.findByText("Zone AE", { selector: "dd" })).toBeInTheDocument();
        expect(term("Chance each year")).toHaveTextContent("1%");
        expect(term("High-risk area (SFHA)")).toHaveTextContent("Yes");
        expect(term("Flood insurance")).toHaveTextContent("Required");
        expect(term("Base flood elevation")).toHaveTextContent("8 feet (NGVD29)");
        expect(term("FEMA map")).toHaveTextContent("12086C, data as of 2026-11-13");
        expect(panel.queryByText(/overlap here/)).not.toBeInTheDocument();

        await userEvent.click(panel.getByText("What does Zone AE mean?"));
        expect(
          panel.getByText("High-risk floodplain with a base flood elevation.", { selector: "p" }),
        ).toBeVisible();
        expect(panel.getByText(/federally regulated lender/)).toBeVisible();
        expect(panel.getByRole("link", { name: "FEMA glossary: Zone AE" })).toHaveAttribute(
          "href",
          "https://www.fema.gov/glossary/ae",
        );
        expect(panel.getByRole("link", { name: "42 U.S.C. 4012a" })).toBeVisible();

        await userEvent.click(panel.getByText("All FEMA flood zones"));
        const table = within(panel.getByRole("table", { name: "All FEMA flood zones" }));
        expect(table.getByRole("rowheader", { name: "Zone X (shaded)" })).toBeInTheDocument();
        expect(table.getByRole("rowheader", { name: "Zone D" })).toBeInTheDocument();
        expect(panel.getByRole("link", { name: "FEMA's Flood Map Service Center" })).toBeVisible();
      });

      it("says when overlapping map areas disagree", async () => {
        const panel = await openWith({ ...mappedAE, fema_zone: "VE", fema_zone_key: "VE", fema_matches: 2, fema_conflict: true });
        expect(await panel.findByText(/2 FEMA map areas overlap here and disagree/)).toBeInTheDocument();
        expect(panel.getByText("Zone VE", { selector: "dd" })).toBeInTheDocument();
      });

      it("keeps shaded and unshaded Zone X apart", async () => {
        const shaded = await openWith({
          fema_status: "mapped",
          fema_zone: "X",
          fema_zone_key: "X_SHADED",
          fema_zone_subtype: "0.2 PCT ANNUAL CHANCE FLOOD HAZARD",
          in_sfha: false,
        });
        expect(await shaded.findByText("Zone X (shaded)", { selector: "dd" })).toBeInTheDocument();
        expect(shaded.getByText("0.2% annual chance flood hazard")).toBeInTheDocument();
        expect(shaded.getByText("Not required", { selector: "dd" })).toBeInTheDocument();
      });

      it.each([
        ["not_mapped", "Not on a FEMA flood map"],
        ["not_us", "Outside the US"],
        ["unavailable", "FEMA data not loaded"],
      ])("explains a %s point, unlike any zone", async (status, label) => {
        const panel = await openWith({ fema_status: status });
        expect(await panel.findByText(label)).toBeInTheDocument();
        expect(panel.queryByText("Zone X (unshaded)", { selector: "dd" })).not.toBeInTheDocument();
        expect(panel.queryByText("Zone D", { selector: "dd" })).not.toBeInTheDocument();
        expect(panel.queryByText("High-risk area (SFHA)", { selector: "dt" })).not.toBeInTheDocument();
        // The explainer offers every zone instead of one.
        await userEvent.click(panel.getByText("What do FEMA flood zones mean?"));
        expect(panel.getByRole("rowheader", { name: "Zone AE" })).toBeVisible();
      });

      it("notes a missing elevation and an unusual SFHA flag", async () => {
        const panel = await openWith({ ...mappedAE, base_flood_elevation: null, in_sfha: false });
        expect(await panel.findByText("Not recorded", { selector: "dd" })).toBeInTheDocument();
        expect(panel.getByText(/FEMA often draws base flood elevations as lines/)).toBeInTheDocument();
        expect(panel.getByText(/outside the high-risk area, which is unusual for Zone AE/)).toBeInTheDocument();
      });

      it("still shows the zone when its explanations can't load", async () => {
        const panel = await openWith(mappedAE, { definitionsFail: true });
        expect(await panel.findByText("Definitions are down")).toBeInTheDocument();
        // The zone key stands in for the label, and the facts from the asset still show.
        expect(panel.getByText("AE", { selector: "dd" })).toBeInTheDocument();
        expect(panel.getByText("8 feet (NGVD29)")).toBeInTheDocument();
        expect(panel.queryByText(/What does/)).not.toBeInTheDocument();
      });
    });

    it("explains why an asset was excluded and shows no chart or map", async () => {
      const excluded = {
        ...asset(3, { assessable: false, exclusion_reason: "off_land", match_type: "none" }),
        geometry_wkt: null,
        impacts: [],
        scores: [],
      };
      const requests = stub({ detail: excluded });
      await renderDashboard();
      await userEvent.click(screen.getByRole("button", { name: "asset-3" }));
      const panel = within(await screen.findByRole("dialog"));
      expect(await panel.findByText(/not near any country/)).toBeInTheDocument();
      expect(panel.queryByLabelText("Chart")).not.toBeInTheDocument();
      expect(requests.some((r) => r.includes("hazard-maps"))).toBe(false);
    });
  });
});
