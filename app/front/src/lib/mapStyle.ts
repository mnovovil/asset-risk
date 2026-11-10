/** Basemap setup shared by every MapLibre map. Only map components import this: it's large. */

import { setWorkerUrl, type StyleSpecification } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

// MapLibre looks for its worker next to its own file, which isn't where a bundler puts it.
setWorkerUrl(workerUrl);

export const LIGHT_STYLE =
  import.meta.env.VITE_MAP_STYLE_LIGHT ?? "https://tiles.openfreemap.org/styles/positron";
export const DARK_STYLE =
  import.meta.env.VITE_MAP_STYLE_DARK ?? "https://tiles.openfreemap.org/styles/dark";

export const basemapStyle = (dark: boolean) => (dark ? DARK_STYLE : LIGHT_STYLE);

/** Ring around a point, matching the panel surface. */
export const pointRing = (dark: boolean) => (dark ? "#1a1a19" : "#ffffff");

/** Points still show on this if the tiles can't be reached. */
export function blankStyle(dark: boolean): StyleSpecification {
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
