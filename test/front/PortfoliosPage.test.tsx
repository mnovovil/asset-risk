import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunStatus } from "@/api/client";
import { AppRoutes } from "@/App";
import { POLL_INTERVAL_MS } from "@/hooks/useRun";

import { CONFIG, jsonResponse, runStatus, SUMMARY, TRAJECTORY } from "./helpers";

vi.mock("@/components/dashboard/RiskMap", () => ({ default: () => null }));
vi.mock("@/components/portfolios/RiskMapThumbnail", () => ({
  default: ({ alt, clusters }: { alt: string; clusters: unknown[] }) => (
    <img alt={alt} data-clusters={clusters.length} />
  ),
}));
vi.mock("@/components/dashboard/HazardTileMap", () => ({ default: () => null }));

const id = (n: number) => `${n}${n}${n}${n}${n}${n}${n}${n}-1111-4111-8111-111111111111`;

const OVERVIEW = {
  summary: SUMMARY,
  trajectory: TRAJECTORY,
  clusters: [],
  points: [
    { row_num: 1, lat: 40.4, lon: -3.7 },
    { row_num: 2, lat: 29.7, lon: -95.3 },
  ],
};

const TOTALS = [
  { row_num: 1, asset_id: "a1", total_aal: 0.01, shared_aal: 0.004, hazards: 2 },
  { row_num: 2, asset_id: "a2", total_aal: 0.03, shared_aal: 0.006, hazards: 2 },
];

type Results = { overview?: unknown; totals?: unknown };

/**
 * Answer the list from a script of responses (the last repeats), and record every request. A
 * completed run's overview and totals come from `results`, by run id, or the defaults above.
 */
function stubList(
  responses: (RunStatus[] | number | "offline")[],
  results: Record<string, Results | number> = {},
) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    requests.push(url);
    if (url === "/api/config") return jsonResponse(CONFIG);
    const match = url.match(/^\/api\/runs\/([^/]+)\/(overview|totals)/);
    if (match) {
      const result = results[decodeURIComponent(match[1])] ?? {};
      if (typeof result === "number") return jsonResponse({ detail: `Error ${result}` }, result);
      return jsonResponse(
        match[2] === "overview" ? (result.overview ?? OVERVIEW) : (result.totals ?? TOTALS),
      );
    }
    if (url !== "/api/runs") throw new Error(`Unexpected request: ${url}`);
    const next = responses.length > 1 ? responses.shift()! : responses[0];
    if (next === "offline") throw new TypeError("Failed to fetch");
    if (typeof next === "number") return jsonResponse({ detail: `Error ${next}` }, next);
    return jsonResponse(next);
  });
  return requests;
}

function renderAt(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

const nextPoll = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });

const listRequests = (requests: string[]) => requests.filter((url) => url === "/api/runs").length;

const cardFor = (name: string) => screen.getByRole("link", { name }).closest("article")!;

describe("PortfoliosPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists each portfolio with its label, size, status and link", async () => {
    const runs = [
      runStatus({ run_id: id(1), source_name: "offices.csv", total_rows: 1200, status: "completed" }),
      runStatus({ run_id: id(2), source_name: null, status: "queued", queue_position: 1 }),
      runStatus({
        run_id: id(3),
        source_name: "stores.csv",
        status: "running",
        stage: "assessing",
        done: 3,
        total: 6,
      }),
      runStatus({ run_id: id(4), source_name: "bad.csv", status: "failed", error: "S3 is down" }),
      runStatus({
        run_id: id(5),
        source_name: "late.csv",
        status: "interrupted",
        error: "The app restarted",
      }),
    ];
    const requests = stubList([runs]);
    renderAt();
    await settle();

    expect(screen.getByRole("link", { name: "offices.csv" })).toHaveAttribute(
      "href",
      `/runs/${id(1)}`,
    );
    const offices = within(cardFor("offices.csv"));
    expect(offices.getByText(/1,200 assets/)).toBeInTheDocument();
    expect(offices.getByText("Results ready")).toBeInTheDocument();
    expect(offices.getByText((_, el) => el?.tagName === "TIME")).toHaveAttribute(
      "datetime",
      "2026-10-30T12:00:00Z",
    );

    expect(
      within(cardFor("Untitled portfolio")).getByText("Waiting to start (number 1 in the queue)"),
    ).toBeInTheDocument();
    expect(
      within(cardFor("stores.csv")).getByText("Running: assessing (3 of 6)"),
    ).toBeInTheDocument();
    const failed = within(cardFor("bad.csv"));
    expect(failed.getByText("Failed")).toBeInTheDocument();
    expect(failed.getByText("S3 is down")).toBeInTheDocument();
    const interrupted = within(cardFor("late.csv"));
    expect(interrupted.getByText("Didn't finish")).toBeInTheDocument();
    expect(interrupted.getByText("The app restarted")).toBeInTheDocument();

    // Results are 409 until a run completes, so only the completed run's results are asked for.
    const perRun = requests.filter((url) => url !== "/api/runs");
    expect(perRun).toEqual([
      `/api/runs/${id(1)}/overview`,
      `/api/runs/${id(1)}/totals?scenario=ssp585&year=2050`,
    ]);
  });

  it("shows a completed portfolio's figures for the pair the dashboard opens on", async () => {
    stubList([[runStatus({ run_id: id(1), source_name: "offices.csv", status: "completed" })]]);
    renderAt();
    await settle();
    const card = within(cardFor("offices.csv"));
    const figure = (label: string) => card.getByText(label).closest(".card-figure")!;

    // ssp585 has the most hazards, and 2050 is nearest mid-century.
    expect(figure("Mean annual loss, equal-weighted")).toHaveTextContent("2.000%");
    expect(figure("Mean annual loss, equal-weighted")).toHaveTextContent(/2050, over 2 hazards/);
    expect(figure("Assets assessed")).toHaveTextContent("2 of 3");
    expect(figure("Assets excluded")).toHaveTextContent("1");
    expect(figure("Building type assumed")).toHaveTextContent("50%");
    expect(figure("Building type assumed")).not.toHaveClass("card-figure-warning");
    expect(card.getByRole("img")).toHaveAttribute(
      "alt",
      "Map of where offices.csv's 2 assets are, coloured by total annual loss",
    );
    // One link per card, so the keyboard stops on each card once.
    expect(card.getAllByRole("link")).toHaveLength(1);
  });

  it("says 'No results' rather than 0% when the pair has none", async () => {
    const trajectory = [
      {
        scenario: "ssp585",
        year: 2050,
        assets: 0,
        mean_total_aal: null,
        mean_shared_aal: null,
        hazards: 0,
      },
    ];
    stubList([[runStatus({ run_id: id(1), source_name: "p.csv", status: "completed" })]], {
      [id(1)]: { overview: { ...OVERVIEW, trajectory }, totals: [] },
    });
    renderAt();
    await settle();
    const loss = within(cardFor("p.csv")).getByText("Mean annual loss, equal-weighted");
    expect(loss.closest(".card-figure")).toHaveTextContent("No results");
    expect(loss.closest(".card-figure")).not.toHaveTextContent("0%");
  });

  it("warns when most building types were assumed", async () => {
    const summary = { ...SUMMARY, assessable: 4, assumed_type: 3 };
    stubList([[runStatus({ run_id: id(1), source_name: "p.csv", status: "completed" })]], {
      [id(1)]: { overview: { ...OVERVIEW, summary } },
    });
    renderAt();
    await settle();
    const assumed = within(cardFor("p.csv")).getByText("Building type assumed");
    expect(assumed.closest(".card-figure")).toHaveClass("card-figure-warning");
    expect(assumed.closest(".card-figure")).toHaveTextContent("75%");
  });

  it("keeps the card and its link when its results don't load", async () => {
    stubList([[runStatus({ run_id: id(1), source_name: "p.csv", status: "completed" })]], {
      [id(1)]: 500,
    });
    renderAt();
    await settle();
    expect(within(cardFor("p.csv")).getByRole("status")).toHaveTextContent("Error 500");
  });

  it("says when no asset could be placed on a map", async () => {
    stubList([[runStatus({ run_id: id(1), source_name: "p.csv", status: "completed" })]], {
      [id(1)]: { overview: { ...OVERVIEW, points: [] } },
    });
    renderAt();
    await settle();
    const card = within(cardFor("p.csv"));
    expect(card.getByText("No asset could be placed on a map.")).toBeInTheDocument();
  });

  it("encodes the run id in its link", async () => {
    stubList([[runStatus({ run_id: "a b/c", source_name: "odd.csv", status: "completed" })]]);
    renderAt();
    await settle();
    expect(screen.getByRole("link", { name: "odd.csv" })).toHaveAttribute(
      "href",
      "/runs/a%20b%2Fc",
    );
  });

  it("points an empty list at the upload page", async () => {
    stubList([[]]);
    renderAt();
    await settle();
    expect(screen.getByText("No portfolios yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Assess a portfolio" })).toHaveAttribute(
      "href",
      "/upload",
    );
    expect(screen.getByRole("link", { name: "New portfolio" })).toHaveAttribute("href", "/upload");
  });

  it("shows loading, then the server's error, and stops", async () => {
    const requests = stubList([500]);
    renderAt();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Error 500");
    await nextPoll();
    expect(listRequests(requests)).toBe(1);
  });

  it("polls while a run is unfinished and stops once all have finished", async () => {
    const running = runStatus({ run_id: id(1), source_name: "p.csv", status: "running" });
    const done = { ...running, status: "completed" };
    const requests = stubList([[running], [done]]);
    renderAt();
    await settle();
    expect(screen.getByText("Running")).toBeInTheDocument();

    await nextPoll();
    expect(screen.getByText("Results ready")).toBeInTheDocument();
    await nextPoll();
    await nextPoll();
    expect(listRequests(requests)).toBe(2);
    // The results are fetched once, however often the list is.
    expect(requests.filter((url) => url.endsWith("/overview"))).toHaveLength(1);
  });

  it("keeps the list when a later poll fails", async () => {
    const running = runStatus({ run_id: id(1), source_name: "p.csv", status: "running" });
    stubList([[running], "offline", [running]]);
    renderAt();
    await settle();
    await nextPoll();
    expect(screen.getByRole("link", { name: "p.csv" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Lost contact");
    await nextPoll();
    expect(screen.queryByText(/Lost contact/)).not.toBeInTheDocument();
  });

  it("serves the upload page at /upload", async () => {
    stubList([[]]);
    renderAt("/upload");
    await settle();
    expect(screen.getByRole("heading", { name: "Assess a portfolio" })).toBeInTheDocument();
  });
});
