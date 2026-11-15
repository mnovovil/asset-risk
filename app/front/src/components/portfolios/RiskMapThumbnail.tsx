/**
 * A still picture of a portfolio's "Where the risk is" map, as the dashboard opens it.
 *
 * Browsers keep only about 16 WebGL contexts per page and drop the oldest past that, so a live map
 * per card would break on a page with many portfolios. Each thumbnail draws one map off screen,
 * saves its canvas as an image and removes the map, and a queue lets only one exist at a time.
 */

import { type CircleLayerSpecification, Map as MapLibre } from "maplibre-gl";
import { useEffect, useState } from "react";

import { usePrefersDark } from "@/hooks/useColorScheme";
import { FIT_PADDING_PX, MAX_FIT_ZOOM } from "@/lib/mapFeatures";
import { basemapStyle, blankStyle, pointRing } from "@/lib/mapStyle";
import { type Thumbnail, thumbnailFeatures } from "@/lib/thumbnail";

import type { AssetTotal, Cluster, MapPoint } from "@/api/client";

// The size drawn off screen, at the card's 16:9. The card scales the image to fit.
const WIDTH_PX = 640;
const HEIGHT_PX = 360;
// Past this, take the picture anyway: a basemap that never finishes still leaves the points.
const GIVE_UP_MS = 15_000;

interface Snapshot {
  src: string;
  /** The basemap's credits, which a picture of it must keep. */
  attribution: string;
}

type State = { kind: "waiting" } | { kind: "ready"; snapshot: Snapshot } | { kind: "unavailable" };

const cache = new Map<string, Snapshot>();
let queue: Promise<unknown> = Promise.resolve();

/** Run one map at a time, in the order asked for. */
function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const next = queue.then(task);
  queue = next.catch(() => undefined);
  return next;
}

function draw(thumbnail: Thumbnail, dark: boolean, cancelled: () => boolean): Promise<Snapshot> {
  return new Promise((resolve, reject) => {
    if (cancelled()) {
      reject(new Error("cancelled"));
      return;
    }
    const container = document.createElement("div");
    container.className = "card-map-offscreen";
    container.style.width = `${WIDTH_PX}px`;
    container.style.height = `${HEIGHT_PX}px`;
    document.body.append(container);

    let map: MapLibre;
    try {
      map = new MapLibre({
        container,
        style: basemapStyle(dark),
        interactive: false,
        attributionControl: { compact: false },
        fadeDuration: 0,
        canvasContextAttributes: { preserveDrawingBuffer: true },
      });
    } catch (error) {
      container.remove();
      reject(error); // no WebGL
      return;
    }

    let finished = false;
    let fellBack = false;
    let loaded = false;
    const timer = setTimeout(() => finish(), GIVE_UP_MS);

    function finish() {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      try {
        const attribution =
          container.querySelector(".maplibregl-ctrl-attrib-inner")?.textContent?.trim() ?? "";
        resolve({ src: map.getCanvas().toDataURL("image/png"), attribution });
      } catch (error) {
        reject(error);
      } finally {
        map.remove();
        container.remove();
      }
    }

    function addPoints() {
      loaded = true;
      const paint: CircleLayerSpecification["paint"] = {
        "circle-color": ["get", "color"],
        "circle-radius": ["get", "radius"],
        "circle-opacity": ["get", "opacity"],
        "circle-stroke-color": ["get", "ring"],
        "circle-stroke-width": 2,
      };
      map.addSource("assets", { type: "geojson", data: thumbnail.features });
      map.addLayer({ id: "assets", type: "circle", source: "assets", paint });
      map.once("idle", finish);
    }

    map.once("style.load", addPoints);
    map.on("error", () => {
      // Tiles failing after load only lose some background. Before load, nothing would draw.
      if (loaded || fellBack) return;
      fellBack = true;
      map.once("style.load", addPoints);
      map.setStyle(blankStyle(dark));
    });

    if (thumbnail.bounds) {
      map.fitBounds(thumbnail.bounds, {
        padding: FIT_PADDING_PX,
        maxZoom: MAX_FIT_ZOOM,
        animate: false,
      });
    }
  });
}

interface RiskMapThumbnailProps {
  runId: string;
  points: MapPoint[];
  clusters: Cluster[];
  totals: AssetTotal[];
  /** Describes the picture, for readers who can't see it. */
  alt: string;
}

export default function RiskMapThumbnail({
  runId,
  points,
  clusters,
  totals,
  alt,
}: RiskMapThumbnailProps) {
  const dark = usePrefersDark();
  const key = `${runId}:${dark ? "dark" : "light"}`;
  const [state, setState] = useState<State>(() => {
    const snapshot = cache.get(key);
    return snapshot ? { kind: "ready", snapshot } : { kind: "waiting" };
  });

  useEffect(() => {
    const cached = cache.get(key);
    if (cached) {
      setState({ kind: "ready", snapshot: cached });
      return;
    }
    setState({ kind: "waiting" });
    let cancelled = false;
    const thumbnail = thumbnailFeatures(points, clusters, totals, dark, pointRing(dark));
    enqueue(() => draw(thumbnail, dark, () => cancelled))
      .then((snapshot) => {
        cache.set(key, snapshot);
        if (!cancelled) setState({ kind: "ready", snapshot });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [key, points, clusters, totals, dark]);

  if (state.kind === "unavailable") {
    return <p className="card-map-placeholder">This browser can't draw the map.</p>;
  }
  if (state.kind === "waiting") {
    return <div className="card-map-placeholder card-map-loading" aria-hidden="true" />;
  }
  return (
    <>
      <img className="card-map-image" src={state.snapshot.src} alt={alt} />
      {state.snapshot.attribution && (
        <span className="card-map-attribution">{state.snapshot.attribution}</span>
      )}
    </>
  );
}
