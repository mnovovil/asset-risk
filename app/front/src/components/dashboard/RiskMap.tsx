import "maplibre-gl/dist/maplibre-gl.css";

import {
  GeoJSONSource,
  Map as MapLibre,
  Popup,
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Asset } from "@/api/client";
import { type AssetRow } from "@/lib/dashboard";
import { assetLabel, percent } from "@/lib/format";
import { NO_RESULT_COLOR, ramp, scoreColor, totalColor } from "@/lib/mapColors";
import { hazardLabel } from "@/lib/hazards";
import { usePrefersDark } from "@/hooks/useColorScheme";

import { COLOR_BY_TOTAL } from "./Filters";

// MapLibre looks for its worker next to its own file, which isn't where a bundler puts it.
setWorkerUrl(workerUrl);

const LIGHT_STYLE =
  import.meta.env.VITE_MAP_STYLE_LIGHT ?? "https://tiles.openfreemap.org/styles/positron";
const DARK_STYLE =
  import.meta.env.VITE_MAP_STYLE_DARK ?? "https://tiles.openfreemap.org/styles/dark";
const SOURCE = "assets";
const LAYER = "assets";
const HIT_RADIUS_PX = 12;
const FIT_PADDING_PX = 48;
const MAX_FIT_ZOOM = 11;

/** Points still show on this if the tiles can't be reached. */
function blankStyle(dark: boolean): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": dark ? "#1a1a19" : "#f9f9f7" },
      },
    ],
  };
}

interface RiskMapProps {
  assets: Asset[];
  rows: AssetRow[];
  colorBy: string;
  selected: number | null;
  onSelect: (rowNum: number) => void;
}

function describe(asset: Asset, row: AssetRow | undefined, colorBy: string): string {
  if (!asset.assessable) return "Excluded";
  if (colorBy === COLOR_BY_TOTAL) return `Total annual loss ${percent(row?.total)}`;
  return `${hazardLabel(colorBy)}: ${row?.scores[colorBy]?.label ?? "No result"}`;
}

function toFeatures(
  assets: Asset[],
  rows: AssetRow[],
  colorBy: string,
  selected: number | null,
  dark: boolean,
): GeoJSON.FeatureCollection {
  const byRow = new Map(rows.map((row) => [row.rowNum, row]));
  const max = Math.max(0, ...rows.map((row) => row.total ?? 0));
  const features: GeoJSON.Feature[] = [];
  for (const asset of assets) {
    if (asset.lat === null || asset.lon === null) continue;
    if (Math.abs(asset.lat) > 90 || Math.abs(asset.lon) > 180) continue;
    const row = byRow.get(asset.row_num);
    let color: string | null = null;
    if (row && colorBy === COLOR_BY_TOTAL && row.total !== null) {
      color = totalColor(row.total, max, dark);
    } else if (row && colorBy !== COLOR_BY_TOTAL && row.scores[colorBy]) {
      color = scoreColor(row.scores[colorBy].score, dark);
    }
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [asset.lon, asset.lat] },
      properties: {
        rowNum: asset.row_num,
        label: assetLabel(asset),
        detail: describe(asset, row, colorBy),
        color: color ?? "rgba(0,0,0,0)",
        ring: color ? (dark ? "#1a1a19" : "#ffffff") : NO_RESULT_COLOR,
        radius: asset.row_num === selected ? 9 : 6,
      },
    });
  }
  return { type: "FeatureCollection", features };
}

export default function RiskMap({ assets, rows, colorBy, selected, onSelect }: RiskMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const dark = usePrefersDark();
  const [unavailable, setUnavailable] = useState(false);
  const [ready, setReady] = useState(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const features = useMemo(
    () => toFeatures(assets, rows, colorBy, selected, dark),
    [assets, rows, colorBy, selected, dark],
  );
  const featuresRef = useRef(features);
  featuresRef.current = features;

  useEffect(() => {
    if (!container.current) return;
    let map: MapLibre;
    try {
      map = new MapLibre({
        container: container.current,
        style: dark ? DARK_STYLE : LIGHT_STYLE,
        attributionControl: { compact: true },
      });
    } catch {
      setUnavailable(true); // no WebGL
      return;
    }
    mapRef.current = map;
    const popup = new Popup({ closeButton: false, closeOnClick: false, offset: 12 });
    let loaded = false;
    let fellBack = false;

    function addPoints() {
      map.addSource(SOURCE, { type: "geojson", data: featuresRef.current });
      map.addLayer({
        id: LAYER,
        type: "circle",
        source: SOURCE,
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": ["get", "radius"],
          "circle-stroke-color": ["get", "ring"],
          "circle-stroke-width": 2,
        },
      });
      setReady(true);
    }

    map.once("style.load", () => {
      loaded = true;
      addPoints();
    });
    map.on("error", () => {
      // Tiles failing after load only lose the background. Before load, nothing would draw.
      if (loaded || fellBack) return;
      fellBack = true;
      map.once("style.load", () => {
        loaded = true;
        addPoints();
      });
      map.setStyle(blankStyle(dark));
    });

    const coordinates = featuresRef.current.features.map(
      (f) => (f.geometry as GeoJSON.Point).coordinates as [number, number],
    );
    if (coordinates.length > 0) {
      const lons = coordinates.map(([lon]) => lon);
      const lats = coordinates.map(([, lat]) => lat);
      map.fitBounds(
        [
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ],
        { padding: FIT_PADDING_PX, maxZoom: MAX_FIT_ZOOM, animate: false },
      );
    }

    const near = (point: { x: number; y: number }) =>
      map.getLayer(LAYER)
        ? map.queryRenderedFeatures(
            [
              [point.x - HIT_RADIUS_PX, point.y - HIT_RADIUS_PX],
              [point.x + HIT_RADIUS_PX, point.y + HIT_RADIUS_PX],
            ],
            { layers: [LAYER] },
          )[0]
        : undefined;

    map.on("mousemove", (event) => {
      const feature = near(event.point);
      map.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        popup.remove();
        return;
      }
      const content = document.createElement("div");
      content.className = "map-popup";
      const title = document.createElement("strong");
      title.textContent = String(feature.properties.label);
      const detail = document.createElement("div");
      detail.textContent = String(feature.properties.detail);
      content.append(title, detail);
      popup
        .setLngLat((feature.geometry as GeoJSON.Point).coordinates as [number, number])
        .setDOMContent(content)
        .addTo(map);
    });
    map.on("click", (event) => {
      const feature = near(event.point);
      if (feature) selectRef.current(Number(feature.properties.rowNum));
    });

    return () => {
      popup.remove();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // Rebuilt only for a change of theme: the data updates below, keeping the reader's view.
  }, [dark]);

  useEffect(() => {
    if (!ready) return;
    (mapRef.current?.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(features);
  }, [features, ready]);

  const colors = ramp(dark);
  const max = Math.max(0, ...rows.map((row) => row.total ?? 0));

  return (
    <section className="panel" aria-labelledby="map-heading">
      <h2 id="map-heading">Where the risk is</h2>
      {unavailable ? (
        <p className="notice notice-warning" role="status">
          This browser can't draw the map. Every asset is in the table below.
        </p>
      ) : (
        <div
          ref={container}
          className="map"
          role="img"
          aria-label="Map of the portfolio's assets. The table below has the same values."
        />
      )}
      <ul className="map-legend">
        {colorBy === COLOR_BY_TOTAL ? (
          <>
            <li>
              <span className="dot" style={{ background: colors[0] }} /> Lowest (0%)
            </li>
            {colors.slice(1, -1).map((color) => (
              <li key={color}>
                <span className="dot" style={{ background: color }} />
              </li>
            ))}
            <li>
              <span className="dot" style={{ background: colors[colors.length - 1] }} /> Highest (
              {percent(max)})
            </li>
          </>
        ) : (
          ["Very low", "Low", "Medium", "High", "Very high"].map((label, index) => (
            <li key={label}>
              <span className="dot" style={{ background: colors[index] }} /> {label}
            </li>
          ))
        )}
        <li>
          <span className="dot dot-hollow" /> No result or excluded
        </li>
      </ul>
    </section>
  );
}
