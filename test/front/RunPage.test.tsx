import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunStatus } from "@/api/client";
import { POLL_INTERVAL_MS } from "@/hooks/useRun";
import { RunPage } from "@/pages/RunPage";

import { jsonResponse, runStatus } from "./helpers";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const STATUS_URL = `/api/runs/${RUN_ID}`;

const SUMMARY = {
  total_assets: 3,
  assessable: 2,
  excluded: 1,
  assumed_type: 1,
  global_curve: 0,
  nearest_match: 0,
  no_building: 0,
  failed_assets: 0,
  exclusions: [{ reason: "invalid", assets: 1 }],
  shared_hazards: ["Wind"],
};

/** Answer status polls from a script of responses; the last one repeats. */
function stubPolls(...responses: (RunStatus | number | "offline")[]) {
  const polls = vi.fn();
  vi.stubGlobal("fetch", async (url: string) => {
    if (url.endsWith("/summary")) return jsonResponse(SUMMARY);
    expect(url).toBe(STATUS_URL);
    const next = responses.length > 1 ? responses.shift()! : responses[0];
    polls();
    if (next === "offline") throw new TypeError("Failed to fetch");
    if (typeof next === "number") return jsonResponse({ detail: `Error ${next}` }, next);
    return jsonResponse(next);
  });
  return polls;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={[`/runs/${RUN_ID}`]}>
      <Routes>
        <Route path="/runs/:runId" element={<RunPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const nextPoll = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });

describe("RunPage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the place in the queue", async () => {
    stubPolls(runStatus({ queue_position: 2 }));
    renderPage();
    await settle();
    expect(screen.getByText(/number 2 in the queue/)).toBeInTheDocument();
  });

  it("shows the current stage and its progress", async () => {
    stubPolls(runStatus({ status: "running", stage: "assessing", done: 3, total: 6 }));
    renderPage();
    await settle();
    expect(screen.getByText("Assessing")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("progressbar", { name: "Assessing progress" })).toHaveAttribute(
      "value",
      "3",
    );
  });

  it("shows no progress bar for a stage that doesn't report progress", async () => {
    stubPolls(runStatus({ status: "running", stage: "classifying" }));
    renderPage();
    await settle();
    expect(screen.getByText("Classifying")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("follows the run and stops polling when it completes", async () => {
    const polls = stubPolls(
      runStatus({ status: "running", stage: "geolocating" }),
      runStatus({ status: "completed" }),
    );
    renderPage();
    await settle();
    expect(screen.getByText("Geolocating")).toBeInTheDocument();

    await nextPoll();
    expect(screen.getByRole("status")).toHaveTextContent("This run has finished.");
    expect(screen.getByText(/2 of 3 assets were assessed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download results as CSV" })).toHaveAttribute(
      "href",
      `${STATUS_URL}/export.csv`,
    );

    const count = polls.mock.calls.length;
    await nextPoll();
    await nextPoll();
    expect(polls).toHaveBeenCalledTimes(count);
  });

  it.each([
    ["failed", "geolocate failed: S3 is down"],
    ["interrupted", "The app restarted before this run finished."],
  ])("shows why a run is %s and stops polling", async (status, error) => {
    const polls = stubPolls(runStatus({ status, error }));
    renderPage();
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent(error);
    await nextPoll();
    expect(polls).toHaveBeenCalledTimes(1);
  });

  it("explains an unknown run and stops polling", async () => {
    const polls = stubPolls(404);
    renderPage();
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Error 404");
    await nextPoll();
    expect(polls).toHaveBeenCalledTimes(1);
  });

  it("keeps trying through a lost connection", async () => {
    stubPolls(
      runStatus({ status: "running", stage: "assessing", done: 1, total: 6 }),
      "offline",
      runStatus({ status: "running", stage: "assessing", done: 2, total: 6 }),
    );
    renderPage();
    await settle();
    await nextPoll();
    expect(screen.getByRole("status")).toHaveTextContent("Lost contact");
    expect(screen.getByText("Assessing")).toBeInTheDocument();

    await nextPoll();
    expect(screen.queryByText(/Lost contact/)).not.toBeInTheDocument();
  });

  it("keeps trying through a server error", async () => {
    const polls = stubPolls(500, runStatus({ status: "completed" }));
    renderPage();
    await settle();
    await nextPoll();
    expect(polls).toHaveBeenCalledTimes(2);
    expect(screen.getByText("This run has finished.")).toBeInTheDocument();
  });

  it("stops polling when the page is left", async () => {
    const polls = stubPolls(runStatus({ status: "running", stage: "assessing" }));
    const view = render(
      <MemoryRouter initialEntries={[`/runs/${RUN_ID}`]}>
        <Routes>
          <Route path="/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await settle();
    const count = polls.mock.calls.length;
    view.unmount();
    await nextPoll();
    expect(polls).toHaveBeenCalledTimes(count);
  });
});
