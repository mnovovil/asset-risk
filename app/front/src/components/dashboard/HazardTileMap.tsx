import "maplibre-gl/dist/maplibre-gl.css";

import { Map as MapLibre } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { absoluteTileUrl } from "@/api/client";
import { basemapStyle, blankStyle, pointRing } from "@/lib/mapStyle";
import { usePrefersDark } from "@/hooks/useColorScheme";

const HAZARD = "hazard";
const ASSET = "asset";
// Hazard pixels are about 1 km at the deepest zoom, so a closer start would show only blocks.
const START_ZOOM = 8;
const MAX_ZOOM = 12;
const TILE_SIZE_PX = 512;

interface HazardTileMapProps {
  lat: number;
  lon: number;
  /** The API's tile URL, or null to show the basemap alone. */
  tileUrl: string | null;
  maxZoom: number;
  label: string;
}

/** A small map centred on one asset, with a physrisk hazard map drawn over the basemap. */
export default function HazardTileMap({ lat, lon, tileUrl, maxZoom, label }: HazardTileMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const dark = usePrefersDark();
  const [unavailable, setUnavailable] = useState(false);
  const [ready, setReady] = useState(false);

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

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (map.getLayer(HAZARD)) map.removeLayer(HAZARD);
    if (map.getSource(HAZARD)) map.removeSource(HAZARD);
    if (!tileUrl) return;
    map.addSource(HAZARD, {
      type: "raster",
      tiles: [absoluteTileUrl(tileUrl)],
      tileSize: TILE_SIZE_PX,
      maxzoom: maxZoom,
    });
    map.addLayer({ id: HAZARD, type: "raster", source: HAZARD }, ASSET);
  }, [ready, tileUrl, maxZoom]);

  if (unavailable) {
    return (
      <p className="notice notice-warning" role="status">
        This browser can't draw the map.
      </p>
    );
  }
  return <div ref={container} className="map asset-map" role="img" aria-label={label} />;
}
