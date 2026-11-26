import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "@/api/client";
import { ChatPanel } from "@/components/dashboard/ChatPanel";
import { answerParts, elapsedLabel, historyFrom } from "@/lib/analyst";

import { jsonResponse } from "./helpers";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const ROWS = new Set([1, 2]);

const SOURCE = {
  n: 1,
  tool: "top_assets",
  args: { scenario: "ssp585", year: 2050 },
  result: { assets: [{ row_num: 2, total_aal: 0.07 }], ranked_by: "total_aal" },
};

function response(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    answer: "Row 2 has the highest loss, 7%. Row 9 isn't in this run.",
    verified: true,
    unverified_numbers: [],
    sources: [SOURCE],
    tool_calls: [SOURCE],
    ...overrides,
  };
}

/** A chat request that answers only when aborted, with what it was sent. */
function hangingFetch() {
  const sent: { url: string; init: RequestInit }[] = [];
  const fetch = vi.fn((url: string, init: RequestInit) => {
    sent.push({ url, init });
    return new Promise<Response>((_, reject) =>
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("The request was aborted", "AbortError")),
      ),
    );
  });
  return { fetch, sent };
}

function renderPanel(onSelect = vi.fn(), enabled = true) {
  render(<ChatPanel runId={RUN_ID} enabled={enabled} rowNums={ROWS} onSelect={onSelect} />);
  return onSelect;
}

async function ask(question = "Which asset is worst?") {
  await userEvent.type(screen.getByLabelText("Question"), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ChatPanel", () => {
  it("isn't there when the analyst is off", () => {
    renderPanel(vi.fn(), false);
    expect(screen.queryByRole("heading", { name: "Ask the analyst" })).toBeNull();
  });

  it("says the results it reads leave this machine", () => {
    renderPanel();
    expect(screen.getByText(/through Anthropic's API, so the results it reads\s+leave this machine/)).toBeTruthy();
  });

  it("shows the answer, and its sources expand to the tool, args and result", async () => {
    const fetch = vi.fn(async () => jsonResponse(response()));
    vi.stubGlobal("fetch", fetch);
    renderPanel();
    await ask();

    expect(await screen.findByText(/has the highest loss, 7%/)).toBeTruthy();
    expect(screen.getByText("Figures verified against the results below.")).toBeTruthy();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/runs/${RUN_ID}/chat`);
    expect(JSON.parse(init.body as string)).toEqual({
      question: "Which asset is worst?",
      history: [],
    });

    const sources = screen.getByText("1 source").closest("details") as HTMLDetailsElement;
    expect(sources.open).toBe(false);
    await userEvent.click(screen.getByText("1 source"));
    expect(sources.open).toBe(true);
    const source = screen.getByText("#1 top_assets").closest("details") as HTMLDetailsElement;
    await userEvent.click(screen.getByText("#1 top_assets"));
    expect(source.open).toBe(true);
    expect(source.textContent).toContain('"scenario": "ssp585"');
    expect(source.textContent).toContain('"total_aal": 0.07');
  });

  it("opens the asset when its row is clicked, and only for rows in the run", async () => {
    vi.stubGlobal("fetch", async () => jsonResponse(response()));
    const onSelect = renderPanel();
    await ask();

    await userEvent.click(await screen.findByRole("button", { name: "Row 2" }));
    expect(onSelect).toHaveBeenCalledWith(2);
    expect(screen.queryByRole("button", { name: "Row 9" })).toBeNull();
  });

  it("marks unverified figures and lists them", async () => {
    const unverified = response({ verified: false, unverified_numbers: ["9%", "12"] });
    vi.stubGlobal("fetch", async () => jsonResponse(unverified));
    renderPanel();
    await ask();

    const marker = await screen.findByText("Unverified figures:");
    expect(marker.parentElement?.textContent).toContain("9% and 12");
    expect(screen.queryByText("Figures verified against the results below.")).toBeNull();
  });

  it("counts the time while it waits", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    vi.stubGlobal("fetch", hangingFetch().fetch);
    renderPanel();
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Slow?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByLabelText("elapsed time").textContent).toBe("0:00");
    await act(async () => {
      vi.advanceTimersByTime(65_000);
    });
    expect(screen.getByLabelText("elapsed time").textContent).toBe("1:05");
    expect((screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("cancels the request", async () => {
    const { fetch, sent } = hangingFetch();
    vi.stubGlobal("fetch", fetch);
    renderPanel();
    await ask("Slow?");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(sent[0].init.signal?.aborted).toBe(true);
    expect(await screen.findByText(/^Cancelled\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("shows the server's error message", async () => {
    vi.stubGlobal("fetch", async () =>
      jsonResponse({ detail: "The analyst's model server can't be reached." }, 503),
    );
    renderPanel();
    await ask();

    expect((await screen.findByRole("alert")).textContent).toBe(
      "The analyst's model server can't be reached.",
    );
  });

  it("sends earlier answers as history", async () => {
    const fetch = vi.fn(async () => jsonResponse(response()));
    vi.stubGlobal("fetch", fetch);
    renderPanel();
    await ask("Which asset is worst?");
    await screen.findByText(/has the highest loss/);
    await ask("Why?");

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const [, init] = fetch.mock.calls[1] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string).history).toEqual([
      { role: "user", content: "Which asset is worst?" },
      { role: "assistant", content: response().answer },
    ]);
  });
});

describe("analyst helpers", () => {
  it("turns only rows in the run into links", () => {
    expect(answerParts("Row 2 and row 9, then row 1.", ROWS)).toEqual([
      { text: "Row 2", rowNum: 2 },
      { text: " and row 9, then " },
      { text: "row 1", rowNum: 1 },
      { text: "." },
    ]);
  });

  it("formats elapsed time", () => {
    expect([elapsedLabel(0), elapsedLabel(7.9), elapsedLabel(192)]).toEqual([
      "0:00",
      "0:07",
      "3:12",
    ]);
  });

  it("sends only answered turns as history", () => {
    expect(
      historyFrom([
        { question: "a", response: response({ answer: "A" }) },
        { question: "b", error: "failed" },
        { question: "c", cancelled: true },
      ]),
    ).toEqual([
      { role: "user", content: "a" },
      { role: "assistant", content: "A" },
    ]);
  });
});
