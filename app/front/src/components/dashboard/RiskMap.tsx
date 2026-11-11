import "maplibre-gl/dist/maplibre-gl.css";

import {
  type CircleLayerSpecification,
  GeoJSONSource,
  Map as MapLibre,
  Popup,
} from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Asset, Cluster } from "@/api/client";
import { type ClusterSummary, clusteredRowNums, summariseClusters } from "@/lib/clusters";
import { type AssetRow } from "@/lib/dashboard";
import { count, percent } from "@/lib/format";
import { NO_RESULT_COLOR, ramp, SCORE_LABELS } from "@/lib/mapColors";
import { COLOR_BY_TOTAL, placeable, toFeatures } from "@/lib/mapFeatures";
import { basemapStyle, blankStyle, pointRing } from "@/lib/mapStyle";
import { usePrefersDark } from "@/hooks/useColorScheme";


const SOURCE = "assets";
const LAYER = "assets";
const ZOOMED_IN_LAYER = "assets-zoomed-in";
const CLUSTER_SOURCE = "clusters";
const CLUSTER_LAYER = "clusters";
// With clusters, the opening view shows only bubbles, until this many zoom levels in. Then they give
// way to every asset.
const CLUSTER_ZOOM_SPAN = 1;
const BUBBLE_OPACITY = 0.8;
const HIT_RADIUS_PX = 12;
const FIT_PADDING_PX = 48;
const MAX_FIT_ZOOM = 11;

interface RiskMapProps {
  assets: Asset[];
  clusters: Cluster[];
  rows: AssetRow[];
  colorBy: string;
  selected: number | null;
  onSelect: (rowNum: number) => void;
}

function toBubbles(summaries: ClusterSummary[], dark: boolean): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: summaries.map((summary) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [summary.lon, summary.lat] },
      properties: {
        clusterId: summary.clusterId,
        label: `${summary.count} nearby assets`,
        detail: summary.detail,
        color: summary.color ?? "rgba(0,0,0,0)",
        ring: summary.color ? pointRing(dark) : NO_RESULT_COLOR,
        radius: summary.radius,
      },
    })),
  };
}

export default function RiskMap({
  assets,
  clusters,
  rows,
  colorBy,
  selected,
  onSelect,
}: RiskMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const dark = usePrefersDark();
  const [unavailable, setUnavailable] = useState(false);
  const [ready, setReady] = useState(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const hasClusters = clusters.length > 0;
  const features = useMemo(
    () => toFeatures(assets, rows, colorBy, selected, dark, pointRing(dark), hasClusters),
    [assets, rows, colorBy, selected, dark, hasClusters],
  );
  // Shown in the legend, so assets outside every bubble don't vanish without a word.
  const outside = useMemo(() => {
    const clustered = clusteredRowNums(clusters);
    return placeable(assets).filter((a) => !clustered.has(a.row_num)).length;
  }, [assets, clusters]);
  const featuresRef = useRef(features);
  featuresRef.current = features;
  const summaries = useMemo(
    () => summariseClusters(clusters, assets, rows, colorBy, dark),
    [clusters, assets, rows, colorBy, dark],
  );
  const bubbles = useMemo(() => toBubbles(summaries, dark), [summaries, dark]);
  const bubblesRef = useRef(bubbles);
  bubblesRef.current = bubbles;
  const boundsRef = useRef(new Map<number, ClusterSummary["bounds"]>());
  boundsRef.current = new Map(summaries.map((s) => [s.clusterId, s.bounds]));

  useEffect(() => {
    if (!container.current) return;
    let map: MapLibre;
    try {
      map = new MapLibre({
        container: container.current,
        style: basemapStyle(dark),
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

    // Set once the opening view is known, below.
    let threshold = 0;

    function addPoints() {
      const paint: CircleLayerSpecification["paint"] = {
        "circle-color": ["get", "color"],
        "circle-radius": ["get", "radius"],
        "circle-stroke-color": ["get", "ring"],
        "circle-stroke-width": 2,
      };
      map.addSource(SOURCE, { type: "geojson", data: featuresRef.current });
      map.addSource(CLUSTER_SOURCE, { type: "geojson", data: bubblesRef.current });
      // Bubbles first, so the selected asset stays on top of one.
      map.addLayer({
        id: CLUSTER_LAYER,
        type: "circle",
        source: CLUSTER_SOURCE,
        maxzoom: threshold,
        paint: { ...paint, "circle-opacity": BUBBLE_OPACITY },
      });
      map.addLayer({
        id: ZOOMED_IN_LAYER,
        type: "circle",
        source: SOURCE,
        minzoom: threshold,
        filter: ["==", ["get", "zoomedIn"], true],
        paint,
      });
      // The selected asset, or every asset when the run has no clusters.
      map.addLayer({
        id: LAYER,
        type: "circle",
        source: SOURCE,
        filter: ["!=", ["get", "zoomedIn"], true],
        paint,
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
    // Relative to the opening view, so bubbles show only there, whatever the portfolio's extent.
    threshold = map.getZoom() + CLUSTER_ZOOM_SPAN;

    const LAYERS = [LAYER, ZOOMED_IN_LAYER, CLUSTER_LAYER];

    const near = (point: { x: number; y: number }) =>
      map.getLayer(LAYER)
        ? map.queryRenderedFeatures(
            [
              [point.x - HIT_RADIUS_PX, point.y - HIT_RADIUS_PX],
              [point.x + HIT_RADIUS_PX, point.y + HIT_RADIUS_PX],
            ],
            { layers: LAYERS },
          )[0]
        : undefined;

    /** Zoom into a bubble, at least far enough for its points to replace it. */
    function openCluster(clusterId: number) {
      const bounds = boundsRef.current.get(clusterId);
      if (!bounds) return;
      const [west, south, east, north] = bounds;
      const camera = map.cameraForBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: FIT_PADDING_PX },
      );
      const fitted = camera?.zoom ?? threshold;
      const zoom = Math.max(threshold, Math.min(fitted, Math.max(MAX_FIT_ZOOM, threshold)));
      map.easeTo({ center: camera?.center ?? [(west + east) / 2, (south + north) / 2], zoom });
    }

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
      if (!feature) return;
      if (feature.layer.id === CLUSTER_LAYER) {
        popup.remove();
        openCluster(Number(feature.properties.clusterId));
      } else {
        selectRef.current(Number(feature.properties.rowNum));
      }
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

  useEffect(() => {
    if (!ready) return;
    (mapRef.current?.getSource(CLUSTER_SOURCE) as GeoJSONSource | undefined)?.setData(bubbles);
  }, [bubbles, ready]);

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
          SCORE_LABELS.map((label, index) => (
            <li key={label}>
              <span className="dot" style={{ background: colors[index] }} /> {label}
            </li>
          ))
        )}
        <li>
          <span className="dot dot-hollow" /> No result or excluded
        </li>
        {hasClusters && (
          <li>
            <span className="dot dot-bubble" /> Bubbles: groups of nearby assets, sized by count and
            coloured by their mean. Zoom in or click one to see each asset
          </li>
        )}
        {hasClusters && outside > 0 && (
          <li>
            {count(outside)} {outside === 1 ? "asset" : "assets"} outside any group{" "}
            {outside === 1 ? "shows" : "show"} when you zoom in
          </li>
        )}
      </ul>
    </section>
  );
}
