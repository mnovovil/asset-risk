const SMALLEST_SHOWN = 0.00001; // 0.001%

/** A fraction of asset value, as a percentage. Zero stays distinct from a very small loss. */
export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value === 0) return "0%";
  if (value < SMALLEST_SHOWN) return "<0.001%";
  return `${(value * 100).toFixed(3)}%`;
}

/** An axis tick: as short as the scale allows. */
export function percentTick(value: number): string {
  if (value === 0) return "0%";
  const asPercent = value * 100;
  return `${Number(asPercent.toPrecision(2))}%`;
}

export const count = (value: number) => value.toLocaleString();

export const assetLabel = (asset: { asset_id: string | null; row_num: number }) =>
  asset.asset_id ?? `Row ${asset.row_num}`;

export function truncate(text: string, length: number): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

export function plural(value: number, one: string, many = `${one}s`): string {
  return `${count(value)} ${value === 1 ? one : many}`;
}

export function joinList(items: string[]): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

const SCENARIO_LABELS: Record<string, string> = {
  historical: "Historical",
  ssp126: "SSP1-2.6",
  ssp245: "SSP2-4.5",
  ssp370: "SSP3-7.0",
  ssp585: "SSP5-8.5",
};

export const scenarioLabel = (scenario: string) => SCENARIO_LABELS[scenario] ?? scenario;
