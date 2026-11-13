import { getFloodZoneDefinitions, type FloodZoneDefinitions } from "@/api/client";

let definitions: Promise<FloodZoneDefinitions> | null = null;

/**
 * What FEMA's flood zones mean, from the API. They never change while the page is open, so they're
 * fetched once; a failure is forgotten so the next panel tries again.
 */
export function loadFloodZoneDefinitions(): Promise<FloodZoneDefinitions> {
  definitions ??= getFloodZoneDefinitions().catch((error: unknown) => {
    definitions = null;
    throw error;
  });
  return definitions;
}

/** For tests, which each stub the API afresh. */
export function forgetFloodZoneDefinitions(): void {
  definitions = null;
}

/** FEMA writes subtypes in capitals, with PCT for percent. */
export function subtypeText(subtype: string): string {
  // Both "0.2 PCT" and "0.2PCT" occur.
  const text = subtype.toLowerCase().replace(/(\d)\s*pct\b/g, "$1%");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function sfhaText(inSfha: boolean | null): string {
  if (inSfha === null) return "Not recorded";
  return inSfha ? "Yes" : "No";
}
