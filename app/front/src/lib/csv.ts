/**
 * A quick look at a portfolio CSV, for feedback before upload. The server decides what's valid.
 * Rows aren't checked here: bad coordinates don't stop a run, they're reported in its results.
 */

export const REQUIRED_COLUMNS = ["id", "lat", "lon"] as const;
const DELIMITERS = [",", ";", "\t", "|"];
export const PREVIEW_ROWS = 5;

export interface CsvInspection {
  /** Required columns the header doesn't have. */
  missing: string[];
  /** The first rows, as [id, lat, lon]. */
  preview: string[][];
  rowCount: number;
}

function detectDelimiter(headerLine: string): string {
  const count = (delimiter: string) => headerLine.split(delimiter).length;
  return DELIMITERS.reduce((best, d) => (count(d) > count(best) ? d : best));
}

/** Split into rows of cells, handling quoted cells that contain delimiters or newlines. */
function* parseRows(text: string, delimiter: string): Generator<string[]> {
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      yield row;
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    yield row;
  }
}

const isBlank = (row: string[]) => row.every((cell) => cell.trim() === "");

export function inspectCsv(raw: string): CsvInspection {
  const text = raw.replace(/^﻿/, "");
  const firstLine = text.split(/\r?\n/, 1)[0] ?? "";
  const rows = parseRows(text, detectDelimiter(firstLine));

  const first = rows.next();
  const header = first.done ? [] : first.value.map((name) => name.trim().toLowerCase());
  const missing = REQUIRED_COLUMNS.filter((name) => !header.includes(name));
  const positions = REQUIRED_COLUMNS.map((name) => header.indexOf(name));

  const preview: string[][] = [];
  let rowCount = 0;
  for (const row of rows) {
    if (isBlank(row)) continue;
    rowCount++;
    if (missing.length === 0 && preview.length < PREVIEW_ROWS) {
      preview.push(positions.map((position) => row[position] ?? ""));
    }
  }
  return { missing, preview, rowCount };
}
