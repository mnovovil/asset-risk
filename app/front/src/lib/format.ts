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

/**
 * An amount in the portfolio's currency, or in plain "value units" when its values have none, so a
 * unitless amount never reads as money. Compact (€1.2M) for headline figures and axis ticks.
 */
export function money(
  amount: number | null | undefined,
  currency: string | null,
  compact = false,
): string {
  if (amount === null || amount === undefined) return "–";
  const notation = compact ? "compact" : "standard";
  if (!currency) {
    const digits = compact ? { maximumSignificantDigits: 3 } : { maximumFractionDigits: 0 };
    return `${new Intl.NumberFormat(undefined, { notation, ...digits }).format(amount)} value units`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      notation,
      // Whole units: cents on a loss estimate claim a precision it doesn't have.
      ...(compact ? { maximumSignificantDigits: 3 } : { maximumFractionDigits: 0 }),
    }).format(amount);
  } catch {
    // A code Intl doesn't know: still show the amount, with the code the file gave.
    return `${new Intl.NumberFormat(undefined, { notation }).format(amount)} ${currency}`;
  }
}
