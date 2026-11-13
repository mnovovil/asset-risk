/** Colours for scenario lines, shared by every chart that draws one line per scenario. */

/** The historical baseline, and any scenario without a slot of its own. */
export const BASELINE_COLOR = "var(--series-other)";

// Fixed per scenario, whichever ones are configured. The two default scenarios get the first two
// slots, which are the easiest pair to tell apart.
const SCENARIO_COLORS: Record<string, string> = {
  ssp245: "var(--series-1)",
  ssp585: "var(--series-2)",
  ssp126: "var(--series-3)",
  ssp370: "var(--series-4)",
};

export const scenarioColor = (scenario: string) => SCENARIO_COLORS[scenario] ?? BASELINE_COLOR;
