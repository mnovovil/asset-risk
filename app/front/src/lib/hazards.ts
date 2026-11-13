/**
 * Each hazard keeps one colour wherever it appears, so a colour never depends on what's on screen.
 * The order is the validated categorical order: don't reorder or generate more.
 */
const HAZARDS: { key: string; label: string; color: string }[] = [
  { key: "RiverineInundation", label: "River flood", color: "var(--series-1)" },
  { key: "CoastalInundation", label: "Coastal flood", color: "var(--series-2)" },
  { key: "Wind", label: "Tropical cyclone wind", color: "var(--series-3)" },
  { key: "Fire", label: "Wildfire", color: "var(--series-4)" },
  { key: "Hail", label: "Hail", color: "var(--series-5)" },
  { key: "PluvialInundation", label: "Surface water flood", color: "var(--series-6)" },
  { key: "ChronicHeat", label: "Chronic heat", color: "var(--series-7)" },
  { key: "Drought", label: "Drought", color: "var(--series-8)" },
];
const BY_KEY = new Map(HAZARDS.map((hazard) => [hazard.key, hazard]));
const OTHER_COLOR = "var(--series-other)";

export const hazardLabel = (key: string) => BY_KEY.get(key)?.label ?? key;
export const hazardColor = (key: string) => BY_KEY.get(key)?.color ?? OTHER_COLOR;

function rank(key: string): number {
  const index = HAZARDS.findIndex((hazard) => hazard.key === key);
  return index === -1 ? HAZARDS.length : index;
}

export const sortHazards = (keys: Iterable<string>) =>
  [...new Set(keys)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
