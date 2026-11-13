import type { HazardGridLayer, HazardGridWindow } from "@/api/client";
import { formatValue } from "@/lib/format";

const cellSize = (km: number) => Number(km.toPrecision(2)).toLocaleString();

interface HazardGridFactsProps {
  layer: HazardGridLayer;
  /** The window drawn on the map, or null when there's none to describe. */
  window: HazardGridWindow | null;
  /** How the scale was chosen, when a scenario is shown next to the baseline. */
  scaleNote: string | null;
}

/** What a hazard grid is, and what it says at the asset. The wording comes from the API. */
export function HazardGridFacts({ layer, window, scaleNote }: HazardGridFactsProps) {
  const drawn = window?.available ? window : null;
  const units = layer.units;
  return (
    <>
      {drawn && drawn.min_value !== null && drawn.max_value !== null && (
        <ul className="map-legend">
          <li>
            {formatValue(drawn.min_value)} {units}
            <span
              className="gradient-key"
              style={{ background: `linear-gradient(to right, ${drawn.legend.join(", ")})` }}
            />
            {formatValue(drawn.max_value)} {units}
          </li>
          <li>
            {drawn.asset_value === null ? (
              <>
                <span className="dot dot-hollow" /> No data at this point
              </>
            ) : (
              <>
                This asset's cell:{" "}
                <strong>
                  {formatValue(drawn.asset_value)} {units}
                </strong>
              </>
            )}
          </li>
        </ul>
      )}
      <p className="panel-note">
        {layer.index_label}
        {drawn?.cell_km &&
          ` · Each cell is about ${cellSize(drawn.cell_km[0])} × ${cellSize(drawn.cell_km[1])} km`}
        {drawn && scaleNote && ` · ${scaleNote}`}.{" "}
        <strong>
          {layer.feeds_damage
            ? "Feeds the damage figures."
            : "Indicator only, not in the damage figures."}
        </strong>{" "}
        {layer.caveat}
      </p>
      <p className="panel-note">
        Dataset: {layer.dataset}. Source: {layer.attribution}. A low value, a cell with no data or a
        coarse cell over a city is not proof of low risk.
      </p>
    </>
  );
}
