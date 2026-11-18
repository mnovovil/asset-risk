/**
 * The PDF report's notes. Every sentence is copied from docs/methodology.md, without its markdown,
 * and a test checks it's still there, so the report can't say something the docs don't.
 */

export interface NoteGroup {
  heading: string;
  sentences: string[];
}

export const REPORT_NOTES: NoteGroup[] = [
  {
    heading: "What the figures mean",
    sentences: [
      "Average annual loss (AAL) is the expected damage per year, as a share of asset value.",
      "It isn't a forecast for any one year.",
      "The portfolio mean is equal-weighted, because a list of id, lat, lon has no asset values.",
    ],
  },
  {
    heading: "Comparing scenarios",
    sentences: [
      "physrisk's data doesn't cover the same hazards in every scenario, and it doesn't warn about this.",
      "Totals from different scenarios therefore can't be compared directly.",
      "Change over time uses only the hazards every scenario has, and names them.",
      "A scenario with no results is shown as having none, not as zero.",
    ],
  },
  {
    heading: "Reading the map",
    sentences: [
      "The colour shows an asset's rank within this portfolio, so the same loss can be a different colour in another portfolio or scenario.",
      "A green bubble or point is not proof of low risk.",
      "Excluded assets are counted and listed, and they never count as low risk.",
    ],
  },
  {
    heading: "Building type",
    sentences: [
      "Most assets will have an assumed type.",
      "The choice affects flood results.",
      "If your portfolio is mostly one type, set that as the default.",
    ],
  },
];

export const REPORT_SOURCE_NOTE =
  "Results from physrisk's default data. Methodology and limits: docs/methodology.md.";
