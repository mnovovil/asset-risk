/**
 * A still picture of a MapLibre map, drawn off screen and removed straight away.
 *
 * Browsers keep only about 16 WebGL contexts per page and drop the oldest past that, so a live map
 * per picture would break on a page with many of them. A queue lets only one off-screen map exist
 * at a time, for the portfolio cards' thumbnails and the PDF report alike.
 */

import { type CircleLayerSpecification, Map as MapLibre } from "maplibre-gl";

import { FIT_PADDING_PX, MAX_FIT_ZOOM } from "@/lib/mapFeatures";
import { basemapStyle, blankStyle } from "@/lib/mapStyle";
import type { Thumbnail } from "@/lib/thumbnail";

// Past this, stop waiting: a basemap that never finishes still leaves the points.
const GIVE_UP_MS = 15_000;

export interface Snapshot {
  /** A PNG data URL, `pixelRatio` times the CSS size. */
  src: string;
  /** The basemap's credits, which a picture of it must keep. */
  attribution: string;
  /** "blank" when the tiles couldn't be reached and only the points were drawn. */
  basemap: "loaded" | "blank";
}

export interface SnapshotOptions {
  /** CSS pixels. */
  width: number;
  height: number;
  /** Device pixels per CSS pixel: 1 for a thumbnail, about 3 for print. */
  pixelRatio?: number;
  dark: boolean;
  /**
   * "fallback" draws the points on a plain background when the tiles fail. "fail" rejects with a
   * {@link SnapshotError} instead, and also when the map doesn't settle in time.
   */
  onBasemapError?: "fallback" | "fail";
  cancelled?: () => boolean;
}

/** Why a picture couldn't be taken, in words a reader can act on. */
export class SnapshotError extends Error {
  constructor(
    readonly reason: "no_webgl" | "tiles" | "timeout" | "cancelled",
    message: string,
  ) {
    super(message);
    this.name = "SnapshotError";
  }
}

let queue: Promise<unknown> = Promise.resolve();

/** Run one map at a time, in the order asked for. */
function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const next = queue.then(task);
  queue = next.catch(() => undefined);
  return next;
}

export function snapshotMap(view: Thumbnail, options: SnapshotOptions): Promise<Snapshot> {
  return enqueue(() => draw(view, options));
}

function draw(view: Thumbnail, options: SnapshotOptions): Promise<Snapshot> {
  const { width, height, pixelRatio = 1, dark, onBasemapError = "fallback" } = options;
  const cancelled = options.cancelled ?? (() => false);
  const strict = onBasemapError === "fail";

  return new Promise((resolve, reject) => {
    if (cancelled()) {
      reject(new SnapshotError("cancelled", "Cancelled."));
      return;
    }
    const container = document.createElement("div");
    container.className = "card-map-offscreen";
    container.style.width = `${width}px`;
    container.style.height = `${height}px`;
    document.body.append(container);

    let map: MapLibre;
    try {
      map = new MapLibre({
        container,
        style: basemapStyle(dark),
        interactive: false,
        attributionControl: { compact: false },
        fadeDuration: 0,
        pixelRatio,
        canvasContextAttributes: { preserveDrawingBuffer: true },
      });
    } catch {
      container.remove();
      reject(new SnapshotError("no_webgl", "This browser can't draw the map."));
      return;
    }

    let finished = false;
    let basemap: Snapshot["basemap"] = "loaded";
    let loaded = false;
    const timer = setTimeout(() => {
      if (strict) fail(new SnapshotError("timeout", "The map tiles took too long to load."));
      else finish();
    }, GIVE_UP_MS);

    function cleanUp() {
      finished = true;
      clearTimeout(timer);
      map.remove();
      container.remove();
    }

    function fail(error: Error) {
      if (finished) return;
      cleanUp();
      reject(error);
    }

    function finish() {
      if (finished) return;
      try {
        const attribution =
          container.querySelector(".maplibregl-ctrl-attrib-inner")?.textContent?.trim() ?? "";
        const src = map.getCanvas().toDataURL("image/png");
        cleanUp();
        resolve({ src, attribution, basemap });
      } catch (error) {
        fail(error as Error);
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
      map.addSource("assets", { type: "geojson", data: view.features });
      map.addLayer({ id: "assets", type: "circle", source: "assets", paint });
      map.once("idle", finish);
    }

    map.once("style.load", addPoints);
    map.on("error", () => {
      if (strict) {
        // A picture for print with holes in the basemap would pass for a complete one.
        fail(new SnapshotError("tiles", "The map tiles didn't load."));
        return;
      }
      // Tiles failing after load only lose some background. Before load, nothing would draw.
      if (loaded || basemap === "blank") return;
      basemap = "blank";
      map.once("style.load", addPoints);
      map.setStyle(blankStyle(dark));
    });

    if (view.bounds) {
      map.fitBounds(view.bounds, { padding: FIT_PADDING_PX, maxZoom: MAX_FIT_ZOOM, animate: false });
    }
  });
}
