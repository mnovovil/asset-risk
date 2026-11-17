import { describe, expect, it, vi } from "vitest";

import { ApiError, createRun, getRun } from "@/api/client";

import { jsonResponse } from "./helpers";

describe("the API client", () => {
  it("raises the server's own message", async () => {
    vi.stubGlobal("fetch", async () => jsonResponse({ detail: "Duplicate ids: a" }, 422));
    const error = await getRun("x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: "Duplicate ids: a" });
  });

  it("copes with an error that isn't JSON", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(getRun("x")).rejects.toMatchObject({
      status: 502,
      message: "The server responded with an error (502).",
    });
  });

  it("explains a lost connection", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(getRun("x")).rejects.toMatchObject({
      status: 0,
      message: "Can't reach the server. Check that it's running.",
    });
  });

  it("escapes run ids in the path", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await getRun("../etc");
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/..%2Fetc", expect.anything());
  });

  it("uploads the file as multipart form data", async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["id,lat,lon\n"], "p.csv");
    await createRun(file);
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });
});
