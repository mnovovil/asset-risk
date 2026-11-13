import { lazy, Suspense, useEffect, useId, useState } from "react";

import {
  ApiError,
  getHazardGrids,
  getHazardGridWindow,
  getHazardMaps,
  type HazardGridLayer,
  type HazardGridWindow,
  type HazardMapLayer,
  type Pair,
  type Theme,
} from "@/api/client";
import { usePrefersDark } from "@/hooks/useColorScheme";
import { assetMapPath } from "@/lib/assetMapRoute";
import { formatValue, scenarioLabel } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";
import { layerGroups, NO_DATA_LABEL, pickLayer, selectable } from "@/lib/hazardLayers";

import { HazardGridFacts } from "./HazardGridFacts";

// The map library is large, and the rest of the panel works without it.
const HazardTileMap = lazy(() => import("./HazardTileMap"));

const HISTORICAL: Pair = { scenario: "historical", year: null };

interface AssetHazardMapProps {
  runId: string;
  rowNum: number;
  pair: Pair;
  lat: number;
  lon: number;
  /** The asset's hazards with results, so the ones with no map are listed too. */
  hazards: string[];
  /** The layer and period to open on, as the full-size page passes them from its address. */
  initialLayer?: string | null;
  initialHistorical?: boolean;
  /** "panel" is the small map in the asset panel, with a link to open "page", the full-size one. */
  variant?: "panel" | "page";
}

/** A list from the API, or why it couldn't be loaded. */
type Loaded<T> = { items: T[]; error: null } | { items: []; error: string };

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function useList<T>(load: (signal: AbortSignal) => Promise<T[]>, fallback: string, key: string) {
  const [state, setState] = useState<{ key: string; value: Loaded<T> } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setState({ key, value: { items, error: null } });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState({ key, value: { items: [], error: message(e, fallback) } });
      });
    return () => controller.abort();
    // `key` stands for everything `load` reads.
  }, [key]);
  return state?.key === key ? state.value : null;
}

type WindowState =
  | { key: string; window: HazardGridWindow; error: null }
  | { key: string; window: null; error: string };

export function AssetHazardMap({
  runId,
  rowNum,
  pair,
  lat,
  lon,
  hazards,
  initialLayer = null,
  initialHistorical = false,
  variant = "panel",
}: AssetHazardMapProps) {
  const [historical, setHistorical] = useState(initialHistorical);
  const [wanted, setWanted] = useState<string | null>(initialLayer);
  const [gridWindow, setGridWindow] = useState<WindowState | null>(null);
  const theme: Theme = usePrefersDark() ? "dark" : "light";
  const selectId = useId();
  const shown = historical || pair.scenario === HISTORICAL.scenario ? HISTORICAL : pair;
  const { scenario, year } = shown;
  const pairKey = `${runId}|${rowNum}|${scenario}|${year}`;

  const flood = useList<HazardMapLayer>(
    (signal) => getHazardMaps(runId, { scenario, year }, signal),
    "The flood maps couldn't be loaded.",
    pairKey,
  );
  const grids = useList<HazardGridLayer>(
    (signal) => getHazardGrids(runId, rowNum, { scenario, year }, signal),
    "The hazard grids couldn't be loaded.",
    pairKey,
  );

  const groups = flood && grids ? layerGroups(flood.items, grids.items, hazards) : [];
  const current = pickLayer(groups, wanted);
  const gridId = current?.kind === "grid" && current.layer.available ? current.id : null;
  const windowKey = gridId ? `${pairKey}|${gridId}|${theme}` : null;

  useEffect(() => {
    if (!gridId || !windowKey) return;
    const controller = new AbortController();
    getHazardGridWindow(runId, rowNum, gridId, { scenario, year }, theme, controller.signal)
      .then((window) => {
        // A layer picked since must not be overwritten by this one arriving late.
        if (!controller.signal.aborted) setGridWindow({ key: windowKey, window, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const error = message(e, "This hazard grid couldn't be loaded.");
        setGridWindow({ key: windowKey, window: null, error });
      });
    return () => controller.abort();
  }, [runId, rowNum, gridId, scenario, year, theme, windowKey]);

  if (!flood || !grids) return <p className="muted">Loading…</p>;
  if (flood.error && grids.error) return <p className="notice notice-warning">{flood.error}</p>;
  if (!current) return <p className="muted">physrisk has no public hazard maps.</p>;

  const pairName = `${scenarioLabel(pair.scenario)}, ${pair.year}`;
  const shownName = shown === HISTORICAL ? "Historical" : pairName;
  const largerMap = assetMapPath(runId, rowNum, {
    pair,
    layer: current.id,
    historical: shown === HISTORICAL && pair.scenario !== HISTORICAL.scenario,
  });
  const loaded = gridWindow && gridWindow.key === windowKey ? gridWindow : null;

  return (
    <div className={`asset-hazard-map asset-hazard-map-${variant}`}>
      <div className="map-controls">
        <label htmlFor={selectId}>
          Layer
          <select id={selectId} value={current.id} onChange={(e) => setWanted(e.target.value)}>
            {groups.map((group) => (
              <optgroup key={group.hazard} label={group.label}>
                {group.options.map((option) => (
                  <option key={option.id} value={option.id} disabled={!selectable(option)}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
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
      {flood.error && <p className="notice notice-warning">{flood.error}</p>}
      {grids.error && <p className="notice notice-warning">{grids.error}</p>}
      {current.kind === "flood" && (
        <FloodLayer
          layer={current.layer}
          lat={lat}
          lon={lon}
          shownName={shownName}
          variant={variant}
        />
      )}
      {current.kind === "grid" && (
        <GridLayer
          layer={current.layer}
          loaded={loaded}
          lat={lat}
          lon={lon}
          shownName={shownName}
          scaleNote={
            shown === HISTORICAL
              ? null
              : `One scale for Historical and ${pairName}, where both have data`
          }
          variant={variant}
        />
      )}
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

interface LayerProps {
  lat: number;
  lon: number;
  shownName: string;
  variant: "panel" | "page";
}

function FloodLayer({
  layer,
  lat,
  lon,
  shownName,
  variant,
}: LayerProps & { layer: HazardMapLayer }) {
  const label =
    `Map around this asset of ${hazardLabel(layer.hazard)} depth, 1 in ` +
    `${layer.return_period} years, ${shownName}. Clear areas have no flood in the data.`;
  return (
    <>
      {layer.reason && <p className="notice notice-warning">{layer.reason}.</p>}
      <Suspense fallback={<p className="muted">Loading the map…</p>}>
        <HazardTileMap
          lat={lat}
          lon={lon}
          overlay={
            layer.tile_url ? { kind: "tiles", url: layer.tile_url, maxZoom: layer.max_zoom } : null
          }
          label={label}
          size={variant === "page" ? "large" : "small"}
        />
      </Suspense>
      <ul className="map-legend">
        <li>
          {layer.min_value} {layer.units}
          <span
            className="gradient-key"
            style={{ background: `linear-gradient(to right, ${layer.legend.join(", ")})` }}
          />
          {layer.max_value} {layer.units} or more
        </li>
        <li>
          <span className="dot dot-hollow" /> No flood in the data
        </li>
      </ul>
      <p className="panel-note">
        Flood depth for a 1-in-{layer.return_period}-year event, the only one physrisk publishes as
        a map, at about 1 km resolution and before any flood protection. No flood in the data is not
        proof of no risk. Other hazards are drawn from their own grids, in the same list.
      </p>
    </>
  );
}

function GridLayer({
  layer,
  loaded,
  lat,
  lon,
  shownName,
  scaleNote,
  variant,
}: LayerProps & { layer: HazardGridLayer; loaded: WindowState | null; scaleNote: string | null }) {
  const facts = (window: HazardGridWindow | null) => (
    <HazardGridFacts layer={layer} window={window} scaleNote={scaleNote} />
  );
  // A layer with nothing to draw replaces the map with a notice, so it never reads as low values.
  if (!layer.available) {
    return (
      <>
        <p className="notice notice-warning" role="status">
          {NO_DATA_LABEL}: {layer.reason}.
        </p>
        {facts(null)}
      </>
    );
  }
  if (!loaded) return <p className="muted">Loading…</p>;
  if (loaded.error !== null) return <p className="notice notice-warning">{loaded.error}</p>;
  const { window } = loaded;
  if (!window.available || !window.image_url || !window.bounds) {
    return (
      <>
        <p className="notice notice-warning" role="status">
          {window.reason ?? "No data around this point"}.
        </p>
        {facts(null)}
      </>
    );
  }
  const atAsset =
    window.asset_value === null
      ? "no data at this point"
      : `${formatValue(window.asset_value)} ${layer.units}`;
  const label = `Map around this asset of ${layer.name}, ${layer.index_label}, ${shownName}. The asset's cell: ${atAsset}.`;
  return (
    <>
      <Suspense fallback={<p className="muted">Loading the map…</p>}>
        <HazardTileMap
          lat={lat}
          lon={lon}
          overlay={{ kind: "image", url: window.image_url, bounds: window.bounds }}
          label={label}
          size={variant === "page" ? "large" : "small"}
        />
      </Suspense>
      {facts(window)}
    </>
  );
}
