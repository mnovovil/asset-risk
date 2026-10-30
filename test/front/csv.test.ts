import { describe, expect, it } from "vitest";

import { inspectCsv, PREVIEW_ROWS } from "@/lib/csv";

describe("inspectCsv", () => {
  it("reads a simple file", () => {
    expect(inspectCsv("id,lat,lon\na,1,2\nb,3,4\n")).toEqual({
      missing: [],
      preview: [
        ["a", "1", "2"],
        ["b", "3", "4"],
      ],
      rowCount: 2,
    });
  });

  it.each([
    ["upper case", "ID,LAT,LON\na,1,2\n"],
    ["spaces", " id , lat , lon \na,1,2\n"],
    ["a byte order mark", "﻿id,lat,lon\na,1,2\n"],
    ["Windows line endings", "id,lat,lon\r\na,1,2\r\n"],
    ["no final newline", "id,lat,lon\na,1,2"],
    ["semicolons", "id;lat;lon\na;1;2\n"],
    ["tabs", "id\tlat\tlon\na\t1\t2\n"],
  ])("accepts %s", (_, text) => {
    const result = inspectCsv(text);
    expect(result.missing).toEqual([]);
    expect(result.preview).toEqual([["a", "1", "2"]]);
  });

  it("shows required columns in order when the file has them in another order", () => {
    expect(inspectCsv("lon,note,id,lat\n2,x,a,1\n").preview).toEqual([["a", "1", "2"]]);
  });

  it("names missing columns", () => {
    expect(inspectCsv("id,lat\na,1\n").missing).toEqual(["lon"]);
    expect(inspectCsv("name,city\nx,y\n").missing).toEqual(["id", "lat", "lon"]);
    expect(inspectCsv("").missing).toEqual(["id", "lat", "lon"]);
  });

  it("handles quoted cells with delimiters, quotes and newlines", () => {
    const result = inspectCsv('id,lat,lon\n"a,b",1,2\n"say ""hi""",3,4\n"two\nlines",5,6\n');
    expect(result.rowCount).toBe(3);
    expect(result.preview.map((row) => row[0])).toEqual(["a,b", 'say "hi"', "two\nlines"]);
  });

  it("ignores blank lines", () => {
    expect(inspectCsv("id,lat,lon\na,1,2\n\n,,\nb,3,4\n\n").rowCount).toBe(2);
  });

  it("limits the preview but counts every row", () => {
    const rows = Array.from({ length: 1000 }, (_, i) => `r${i},1,2`).join("\n");
    const result = inspectCsv(`id,lat,lon\n${rows}\n`);
    expect(result.rowCount).toBe(1000);
    expect(result.preview).toHaveLength(PREVIEW_ROWS);
  });

  it("keeps bad coordinates, which the server reports in the results", () => {
    expect(inspectCsv("id,lat,lon\na,abc,\n").preview).toEqual([["a", "abc", ""]]);
  });
});
