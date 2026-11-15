import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunStatus } from "@/api/client";
import { AppRoutes } from "@/App";
import { POLL_INTERVAL_MS } from "@/hooks/useRun";

import { CONFIG, jsonResponse, runStatus } from "./helpers";

vi.mock("@/components/dashboard/RiskMap", () => ({ default: () => null }));
vi.mock("@/components/dashboard/HazardTileMap", () => ({ default: () => null }));

const id = (n: number) => `${n}${n}${n}${n}${n}${n}${n}${n}-1111-4111-8111-111111111111`;

/** Answer the list from a script of responses (the last repeats), and record every request. */
function stubList(...responses: (RunStatus[] | number | "offline")[]) {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    requests.push(url);
    if (url === "/api/config") return jsonResponse(CONFIG);
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

const rowFor = (name: string) => screen.getByRole("link", { name }).closest("tr")!;

describe("PortfoliosPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists each portfolio with its label, size, status and link", async () => {
    const requests = stubList([
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
    ]);
    renderAt();
    await settle();

    expect(screen.getByRole("link", { name: "offices.csv" })).toHaveAttribute(
      "href",
      `/runs/${id(1)}`,
    );
    const offices = within(rowFor("offices.csv"));
    expect(offices.getByText("1,200")).toBeInTheDocument();
    expect(offices.getByText("Results ready")).toBeInTheDocument();
    expect(offices.getByText((_, el) => el?.tagName === "TIME")).toHaveAttribute(
      "datetime",
      "2026-10-30T12:00:00Z",
    );

    expect(
      within(rowFor("Untitled portfolio")).getByText("Waiting to start (number 1 in the queue)"),
    ).toBeInTheDocument();
    expect(
      within(rowFor("stores.csv")).getByText("Running: assessing (3 of 6)"),
    ).toBeInTheDocument();
    const failed = within(rowFor("bad.csv"));
    expect(failed.getByText("Failed")).toBeInTheDocument();
    expect(failed.getByText("S3 is down")).toBeInTheDocument();
    const interrupted = within(rowFor("late.csv"));
    expect(interrupted.getByText("Didn't finish")).toBeInTheDocument();
    expect(interrupted.getByText("The app restarted")).toBeInTheDocument();

    // Results are 409 until a run completes, so the list asks for nothing per run.
    expect(requests.every((url) => url === "/api/runs")).toBe(true);
  });

  it("encodes the run id in its link", async () => {
    stubList([runStatus({ run_id: "a b/c", source_name: "odd.csv", status: "completed" })]);
    renderAt();
    await settle();
    expect(screen.getByRole("link", { name: "odd.csv" })).toHaveAttribute(
      "href",
      "/runs/a%20b%2Fc",
    );
  });

  it("points an empty list at the upload page", async () => {
    stubList([]);
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
    const requests = stubList(500);
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
    const requests = stubList([running], [done]);
    renderAt();
    await settle();
    expect(screen.getByText("Running")).toBeInTheDocument();

    await nextPoll();
    expect(screen.getByText("Results ready")).toBeInTheDocument();
    await nextPoll();
    await nextPoll();
    expect(listRequests(requests)).toBe(2);
  });

  it("keeps the list when a later poll fails", async () => {
    const running = runStatus({ run_id: id(1), source_name: "p.csv", status: "running" });
    stubList([running], "offline", [running]);
    renderAt();
    await settle();
    await nextPoll();
    expect(screen.getByRole("link", { name: "p.csv" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Lost contact");
    await nextPoll();
    expect(screen.queryByText(/Lost contact/)).not.toBeInTheDocument();
  });

  it("serves the upload page at /upload", async () => {
    stubList([]);
    renderAt("/upload");
    await settle();
    expect(screen.getByRole("heading", { name: "Assess a portfolio" })).toBeInTheDocument();
  });
});
