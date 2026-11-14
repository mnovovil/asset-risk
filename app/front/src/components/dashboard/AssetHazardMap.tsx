import { lazy, Suspense, useEffect, useId, useState } from "react";

import { ApiError, getHazardMaps, type HazardMapLayer, type Pair } from "@/api/client";
import { assetMapPath } from "@/lib/assetMapRoute";
import { scenarioLabel } from "@/lib/format";
import { hazardLabel, sortHazards } from "@/lib/hazards";

// The map library is large, and the rest of the panel works without it.
const HazardTileMap = lazy(() => import("./HazardTileMap"));

const HISTORICAL: Pair = { scenario: "historical", year: null };

const withUnits = (value: number, units: string) => (units ? `${value} ${units}` : `${value}`);

interface AssetHazardMapProps {
  runId: string;
  rowNum: number;
  pair: Pair;
  lat: number;
  lon: number;
  /** The asset's hazards with results, so the ones with no map are listed too. */
  hazards: string[];
  /** The hazard and period to open on, as the full-size page passes them from its address. */
  initialHazard?: string | null;
  initialHistorical?: boolean;
  /** "panel" is the small map in the asset panel, with a link to open "page", the full-size one. */
  variant?: "panel" | "page";
}

export function AssetHazardMap({
  runId,
  rowNum,
  pair,
  lat,
  lon,
  hazards,
  initialHazard = null,
  initialHistorical = false,
  variant = "panel",
}: AssetHazardMapProps) {
  const [historical, setHistorical] = useState(initialHistorical);
  const [layers, setLayers] = useState<HazardMapLayer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hazard, setHazard] = useState<string | null>(initialHazard);
  const selectId = useId();
  const shown = historical || pair.scenario === HISTORICAL.scenario ? HISTORICAL : pair;
  const { scenario, year } = shown;

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getHazardMaps(runId, { scenario, year }, controller.signal)
      .then(setLayers)
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "The hazard maps couldn't be loaded.");
      });
    return () => controller.abort();
  }, [runId, scenario, year]);

  if (error) return <p className="notice notice-warning">{error}</p>;
  if (!layers) return <p className="muted">Loading…</p>;

  const mappable = new Map(layers.map((layer) => [layer.hazard, layer]));
  const options = sortHazards([...layers.map((layer) => layer.hazard), ...hazards]);
  const current = mappable.get(hazard ?? "") ?? layers[0];
  if (!current) return <p className="muted">physrisk has no public hazard maps.</p>;
  const pairName = `${scenarioLabel(pair.scenario)}, ${pair.year}`;
  const shownName = shown === HISTORICAL ? "Historical" : pairName;
  const event = current.return_period === null ? "" : `, 1 in ${current.return_period} years`;
  const label =
    `Map around this asset of ${hazardLabel(current.hazard)}: ${current.measure}${event}, ` +
    `${shownName}. Clear areas: ${current.no_data_label}.`;

  const largerMap = assetMapPath(runId, rowNum, {
    pair,
    hazard: current.hazard,
    historical: shown === HISTORICAL && pair.scenario !== HISTORICAL.scenario,
  });

  return (
    <div className={`asset-hazard-map asset-hazard-map-${variant}`}>
      <div className="map-controls">
        <label htmlFor={selectId}>
          Hazard
          <select
            id={selectId}
            value={current.hazard}
            onChange={(event) => setHazard(event.target.value)}
          >
            {options.map((key) => (
              <option key={key} value={key} disabled={!mappable.has(key)}>
                {hazardLabel(key)}
                {mappable.has(key) ? "" : " (no public map)"}
              </option>
            ))}
          </select>
        </label>
        {pair.scenario !== HISTORICAL.scenario && (
          <fieldset className="segmented">
            <legend>Period</legend>
            <label>
              <input
                type="radio"
                name={`${selectId}-period`}
                checked={historical}
                onChange={() => setHistorical(true)}
              />
              Historical
            </label>
            <label>
              <input
                type="radio"
                name={`${selectId}-period`}
                checked={!historical}
                onChange={() => setHistorical(false)}
              />
              {pairName}
            </label>
          </fieldset>
        )}
      </div>
      {current.available ? (
        <>
          <Suspense fallback={<p className="muted">Loading the map…</p>}>
            <HazardTileMap
              lat={lat}
              lon={lon}
              tileUrl={current.tile_url}
              maxZoom={current.max_zoom}
              label={label}
              size={variant === "page" ? "large" : "small"}
            />
          </Suspense>
          <ul className="map-legend" aria-label={`Legend: ${current.measure}`}>
            <li>
              {withUnits(current.min_value, current.units)}
              <span
                className="gradient-key"
                style={{ background: `linear-gradient(to right, ${current.legend.join(", ")})` }}
              />
              {withUnits(current.max_value, current.units)} or more
            </li>
            <li>
              <span className="dot dot-hollow" /> {current.no_data_label}
            </li>
          </ul>
        </>
      ) : (
        <p className="notice notice-warning" role="status">
          {current.reason ?? "No map for this period"}.
        </p>
      )}
      <p className="panel-note">{current.note}</p>
      <p className="panel-note">{current.source}</p>
      {variant === "panel" && (
        <p>
          <a
            className="button"
            href={largerMap}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open a larger map in a new tab"
          >
            Open larger map ↗
          </a>
        </p>
      )}
    </div>
  );
}
