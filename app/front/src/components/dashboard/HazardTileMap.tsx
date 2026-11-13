import "maplibre-gl/dist/maplibre-gl.css";

import { Map as MapLibre } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { absoluteTileUrl } from "@/api/client";
import { basemapStyle, blankStyle, pointRing } from "@/lib/mapStyle";
import { usePrefersDark } from "@/hooks/useColorScheme";

const HAZARD = "hazard";
const ASSET = "asset";
// Close enough to see the streets around the asset. physrisk's tiles stop at zoom 6, so MapLibre
// stretches the one tile that covers the asset: panning and zooming here fetch nothing new.
const START_ZOOM = 14;
const MAX_ZOOM = 17;
const TILE_SIZE_PX = 512;
const FIT_PADDING_PX = 16;

/** What to draw over the basemap: physrisk's flood tiles, or one hazard grid's window. */
export type MapOverlay =
  | { kind: "tiles"; url: string; maxZoom: number }
  /** bounds are west, south, east, north. East can pass 180 when the window crosses it. */
  | { kind: "image"; url: string; bounds: number[] };

interface HazardTileMapProps {
  lat: number;
  lon: number;
  /** The API's tile or image URL, or null to show the basemap alone. */
  overlay: MapOverlay | null;
  label: string;
  /** "small" fits the asset panel; "large" fills the full-size page. */
  size?: "small" | "large";
}

/**
 * A map centred on one asset, with a physrisk hazard map drawn over the basemap. Flood tiles open
 * at street level. A grid's window is fitted whole, about 200 km across, since its cells are
 * kilometres wide.
 */
export default function HazardTileMap({
  lat,
  lon,
  overlay,
  label,
  size = "small",
}: HazardTileMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const dark = usePrefersDark();
  const [unavailable, setUnavailable] = useState(false);
  const [ready, setReady] = useState(false);
  // What the camera was last set for: a grid's bounds, or "street" for the asset at START_ZOOM.
  const framed = useRef("street");

  useEffect(() => {
    if (!container.current) return;
    let map: MapLibre;
    try {
      map = new MapLibre({
        container: container.current,
        style: basemapStyle(dark),
        center: [lon, lat],
        zoom: START_ZOOM,
        maxZoom: MAX_ZOOM,
        attributionControl: { compact: true },
      });
    } catch {
      setUnavailable(true); // no WebGL
      return;
    }
    mapRef.current = map;
    framed.current = "street";
    let loaded = false;
    let fellBack = false;

    function addAsset() {
      map.addSource(ASSET, {
        type: "geojson",
        data: { type: "Point", coordinates: [lon, lat] },
      });
      map.addLayer({
        id: ASSET,
        type: "circle",
        source: ASSET,
        paint: {
          "circle-color": "#0b0b0b",
          "circle-radius": 6,
          "circle-stroke-color": pointRing(dark),
          "circle-stroke-width": 2,
        },
      });
      setReady(true);
    }

    map.once("style.load", () => {
      loaded = true;
      addAsset();
    });
    map.on("error", () => {
      // A missing hazard tile after load is just transparent. Before load, nothing would draw.
      if (loaded || fellBack) return;
      fellBack = true;
      map.once("style.load", () => {
        loaded = true;
        addAsset();
      });
      map.setStyle(blankStyle(dark));
    });

    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [dark, lat, lon]);

  const kind = overlay?.kind ?? null;
  const url = overlay?.url ?? null;
  const maxZoom = overlay?.kind === "tiles" ? overlay.maxZoom : null;
  const bounds = overlay?.kind === "image" ? overlay.bounds.join(",") : null;

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (map.getLayer(HAZARD)) map.removeLayer(HAZARD);
    if (map.getSource(HAZARD)) map.removeSource(HAZARD);
    if (!kind || !url) return;
    if (kind === "tiles") {
      map.addSource(HAZARD, {
        type: "raster",
        tiles: [absoluteTileUrl(url)],
        tileSize: TILE_SIZE_PX,
        maxzoom: maxZoom ?? undefined,
      });
      if (framed.current !== "street") {
        map.jumpTo({ center: [lon, lat], zoom: START_ZOOM });
        framed.current = "street";
      }
    } else if (bounds) {
      const [west, south, east, north] = bounds.split(",").map(Number);
      map.addSource(HAZARD, {
        type: "image",
        url: absoluteTileUrl(url),
        coordinates: [
          [west, north],
          [east, north],
          [east, south],
          [west, south],
        ],
      });
      // Switching between grids on the same cells keeps the reader's own pan and zoom.
      if (framed.current !== bounds) {
        map.fitBounds(
          [
            [west, south],
            [east, north],
          ],
          { padding: FIT_PADDING_PX, animate: false },
        );
        framed.current = bounds;
      }
    }
    map.addLayer(
      {
        id: HAZARD,
        type: "raster",
        source: HAZARD,
        // Sharp cells show the data's real resolution, instead of smoothing it into false detail.
        paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 },
      },
      ASSET,
    );
  }, [ready, kind, url, maxZoom, bounds, lat, lon]);

  if (unavailable) {
    return (
      <p className="notice notice-warning" role="status">
        This browser can't draw the map.
      </p>
    );
  }
  return <div ref={container} className={`map ${size === "large" ? "asset-map-large" : "asset-map"}`} role="img" aria-label={label} />;
}
