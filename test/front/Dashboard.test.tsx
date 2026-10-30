import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/components/dashboard/Dashboard";

import { asset, jsonResponse, resultsResponse, SUMMARY, TRAJECTORY } from "./helpers";

vi.mock("@/components/dashboard/RiskMap", () => ({
  default: ({ colorBy, assets }: { colorBy: string; assets: unknown[] }) => (
    <p>
      Map of {assets.length} assets by {colorBy}
    </p>
  ),
}));

const RUN = "run-1";

function stub(overrides: Record<string, unknown> = {}) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    requests.push(url);
    if (url.includes("hazard-curve")) {
      return jsonResponse({ return_periods: [100], intensities: [0.5] });
    }
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
  return screen.findByRole("heading", { name: "Risk by asset and hazard" });
}

const meanLoss = () =>
  within(screen.getByText("Mean annual loss, equal-weighted").parentElement as HTMLElement);
const scoreTable = () => within(screen.getByRole("region", { name: "Risk by asset and hazard" }));

const rowFor = (name: string) => screen.getByRole("button", { name }).closest("tr") as HTMLElement;

describe("Dashboard", () => {
  beforeEach(() => {
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
    expect(screen.getByText("Map of 3 assets by total")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Colour the map by"), "Fire");
    expect(screen.getByText("Map of 3 assets by Fire")).toBeInTheDocument();
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
      expect(panel.getByText("0.200%")).toBeInTheDocument();
      expect(panel.queryByText("90.000%")).not.toBeInTheDocument();
      expect(panel.getByText("No model")).toBeInTheDocument();
    });

    it("loads the hazard curve with a table twin", async () => {
      const panel = within(await openPanel());
      expect(await panel.findAllByRole("cell", { name: "0.50 m" })).toHaveLength(2);
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

    it("explains why an asset was excluded and asks for no curve", async () => {
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
      expect(requests.some((r) => r.includes("hazard-curve"))).toBe(false);
    });
  });
});
