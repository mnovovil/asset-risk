import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { REPORT_NOTES } from "@/lib/reportText";

/** The methodology as plain text: no emphasis or code marks, one space between words. */
const methodology = readFileSync(resolve(__dirname, "../../docs/methodology.md"), "utf8")
  .replace(/\*\*|`/g, "")
  .replace(/\s+/g, " ");

describe("REPORT_NOTES", () => {
  const sentences = REPORT_NOTES.flatMap((group) => group.sentences);

  it.each(sentences)("is worded as in docs/methodology.md: %s", (sentence) => {
    // A sentence may end the report's note where the docs carry on.
    expect(methodology).toContain(sentence.replace(/\.$/, ""));
  });
});
