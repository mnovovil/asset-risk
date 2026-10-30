import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UploadPage } from "@/pages/UploadPage";

import { CONFIG, fakeFetch, jsonResponse, runStatus } from "./helpers";

function RunStub() {
  return <p>Run page for {useParams().runId}</p>;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/runs/:runId" element={<RunStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

const csv = (text: string, name = "portfolio.csv") => new File([text], name, { type: "text/csv" });
const GOOD = "id,lat,lon\na,1,2\nb,3,4\n";

async function choose(file: File) {
  await userEvent.upload(screen.getByLabelText("Choose a file"), file);
}

describe("UploadPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      fakeFetch({
        "GET /api/config": () => jsonResponse(CONFIG),
        "GET /api/runs": () => jsonResponse([]),
      }),
    );
  });

  it("offers a sample file and states the limits", async () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Download a sample CSV" })).toHaveAttribute(
      "href",
      "/sample_portfolio.csv",
    );
    expect(await screen.findByText(/Limits: 3 rows, 1 MB/)).toBeInTheDocument();
  });

  it("previews a good file before uploading", async () => {
    renderPage();
    await choose(csv(GOOD));
    expect(await screen.findByRole("heading", { name: "portfolio.csv" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "2 rows" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "a" })).toBeInTheDocument();
  });

  it("accepts a dropped file", async () => {
    renderPage();
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [csv(GOOD)] } });
    expect(await screen.findByRole("heading", { name: "portfolio.csv" })).toBeInTheDocument();
  });

  it("explains missing columns and offers no upload", async () => {
    renderPage();
    await choose(csv("id,lat\na,1\n"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "portfolio.csv is missing the column lon.",
    );
    expect(screen.queryByRole("button", { name: /Assess/ })).not.toBeInTheDocument();
  });

  it("rejects a file with no rows", async () => {
    renderPage();
    await choose(csv("id,lat,lon\n"));
    expect(await screen.findByRole("alert")).toHaveTextContent("has no rows");
  });

  it("rejects too many rows", async () => {
    renderPage();
    await screen.findByText(/Limits/);
    await choose(csv("id,lat,lon\na,1,2\nb,1,2\nc,1,2\nd,1,2\n"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The limit is 3");
  });

  it("rejects a file over the size limit without reading it", async () => {
    renderPage();
    await screen.findByText(/Limits/);
    const huge = csv("x");
    Object.defineProperty(huge, "size", { value: 2 * 1024 * 1024 });
    const read = vi.spyOn(huge, "text");
    await choose(huge);
    expect(await screen.findByRole("alert")).toHaveTextContent("over the 1 MB limit");
    expect(read).not.toHaveBeenCalled();
  });

  it("clears an earlier problem when a good file is chosen", async () => {
    renderPage();
    await choose(csv("id,lat\na,1\n"));
    await screen.findByRole("alert");
    await choose(csv(GOOD));
    await screen.findByRole("heading", { name: "portfolio.csv" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("uploads and goes to the run", async () => {
    const run = runStatus({ run_id: "abc" });
    vi.stubGlobal(
      "fetch",
      fakeFetch({
        "GET /api/config": () => jsonResponse(CONFIG),
        "GET /api/runs": () => jsonResponse([]),
        "POST /api/runs": () => jsonResponse(run, 202),
      }),
    );
    renderPage();
    await choose(csv(GOOD));
    await userEvent.click(await screen.findByRole("button", { name: "Assess this portfolio" }));
    expect(await screen.findByText("Run page for abc")).toBeInTheDocument();
  });

  it.each([
    [413, "The file is over the 1 MB limit"],
    [422, "Duplicate ids must be removed: a"],
  ])("shows the server's message for a %i", async (status, detail) => {
    vi.stubGlobal(
      "fetch",
      fakeFetch({
        "GET /api/config": () => jsonResponse(CONFIG),
        "GET /api/runs": () => jsonResponse([]),
        "POST /api/runs": () => jsonResponse({ detail }, status),
      }),
    );
    renderPage();
    await choose(csv(GOOD));
    await userEvent.click(await screen.findByRole("button", { name: "Assess this portfolio" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.getByRole("button", { name: "Assess this portfolio" })).toBeEnabled();
  });

  it("still works when the config and runs list can't load", async () => {
    vi.stubGlobal(
      "fetch",
      fakeFetch({
        "GET /api/config": () => jsonResponse({ detail: "down" }, 500),
        "GET /api/runs": () => jsonResponse({ detail: "down" }, 500),
      }),
    );
    renderPage();
    await choose(csv(GOOD));
    expect(await screen.findByRole("button", { name: "Assess this portfolio" })).toBeEnabled();
  });

  it("lists past runs with links, rendering file names as text", async () => {
    const name = "<img src=x onerror=alert(1)>.csv";
    vi.stubGlobal(
      "fetch",
      fakeFetch({
        "GET /api/config": () => jsonResponse(CONFIG),
        "GET /api/runs": () =>
          jsonResponse([runStatus({ run_id: "abc", source_name: name, status: "completed" })]),
      }),
    );
    renderPage();
    const link = await screen.findByRole("link", { name });
    expect(link).toHaveAttribute("href", "/runs/abc");
    expect(screen.getByText("Completed")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("img")).toBeNull());
  });
});
