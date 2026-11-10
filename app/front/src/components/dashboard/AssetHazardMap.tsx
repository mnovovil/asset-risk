import { lazy, Suspense, useEffect, useId, useState } from "react";

import { ApiError, getHazardMaps, type HazardMapLayer, type Pair } from "@/api/client";
import { scenarioLabel } from "@/lib/format";
import { hazardLabel, sortHazards } from "@/lib/hazards";

// The map library is large, and the rest of the panel works without it.
const HazardTileMap = lazy(() => import("./HazardTileMap"));

const HISTORICAL: Pair = { scenario: "historical", year: null };

interface AssetHazardMapProps {
  runId: string;
  pair: Pair;
  lat: number;
  lon: number;
  /** The asset's hazards with results, so the ones with no map are listed too. */
  hazards: string[];
}

export function AssetHazardMap({ runId, pair, lat, lon, hazards }: AssetHazardMapProps) {
  const [historical, setHistorical] = useState(false);
  const [layers, setLayers] = useState<HazardMapLayer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hazard, setHazard] = useState<string | null>(null);
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
  const label =
    `Map around this asset of ${hazardLabel(current.hazard)} depth, 1 in ` +
    `${current.return_period} years, ${shownName}. Clear areas have no flood in the data.`;

  return (
    <div className="asset-hazard-map">
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
      {current.reason && <p className="notice notice-warning">{current.reason}.</p>}
      <Suspense fallback={<p className="muted">Loading the map…</p>}>
        <HazardTileMap
          lat={lat}
          lon={lon}
          tileUrl={current.tile_url}
          maxZoom={current.max_zoom}
          label={label}
        />
      </Suspense>
      <ul className="map-legend">
        <li>
          {current.min_value} {current.units}
          <span
            className="gradient-key"
            style={{ background: `linear-gradient(to right, ${current.legend.join(", ")})` }}
          />
          {current.max_value} {current.units} or more
        </li>
        <li>
          <span className="dot dot-hollow" /> No flood in the data
        </li>
      </ul>
      <p className="panel-note">
        Flood depth for a 1-in-{current.return_period}-year event, the only one physrisk publishes
        as a map, at about 1 km resolution and before any flood protection. No flood in the data is
        not proof of no risk. Other hazards have no public map data.
      </p>
    </div>
  );
}
