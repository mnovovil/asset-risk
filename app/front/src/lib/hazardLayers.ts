/**
 * The hazard map picker's options: physrisk's flood maps and its hazard grids, grouped by hazard.
 *
 * A flood layer's id is its hazard key (`RiverineInundation`) and a grid's id is the API's
 * (`wind_iris_max_speed`), so the two never collide. A hazard with results but neither kind of map
 * stays listed, disabled, so its absence is visible.
 */

import type { HazardGridLayer, HazardMapLayer } from "@/api/client";
import { hazardLabel, sortHazards } from "@/lib/hazards";

export const NO_DATA_LABEL = "No data for this scenario/year";
const DAMAGE_MARK = "used in damage figures";

export type LayerOption =
  | { kind: "flood"; id: string; hazard: string; label: string; layer: HazardMapLayer }
  | { kind: "grid"; id: string; hazard: string; label: string; layer: HazardGridLayer }
  | { kind: "none"; id: string; hazard: string; label: string };

export interface LayerGroup {
  hazard: string;
  label: string;
  options: LayerOption[];
}

const withNoData = (label: string, available: boolean) =>
  available ? label : `${label} · ${NO_DATA_LABEL}`;

function floodOption(layer: HazardMapLayer): LayerOption {
  const label = `Flood depth · 1 in ${layer.return_period} years`;
  return {
    kind: "flood",
    id: layer.hazard,
    hazard: layer.hazard,
    label: withNoData(label, layer.available),
    layer,
  };
}

function gridOption(layer: HazardGridLayer): LayerOption {
  const parts = [layer.name, layer.index_label, ...(layer.feeds_damage ? [DAMAGE_MARK] : [])];
  return {
    kind: "grid",
    id: layer.id,
    hazard: layer.hazard,
    label: withNoData(parts.join(" · "), layer.available),
    layer,
  };
}

export function layerGroups(
  flood: HazardMapLayer[],
  grids: HazardGridLayer[],
  resultHazards: string[] = [],
): LayerGroup[] {
  const options = [...flood.map(floodOption), ...grids.map(gridOption)];
  return sortHazards([...options.map((option) => option.hazard), ...resultHazards]).map(
    (hazard) => {
      const own = options.filter((option) => option.hazard === hazard);
      return {
        hazard,
        label: hazardLabel(hazard),
        options: own.length
          ? own
          : [{ kind: "none", id: `none:${hazard}`, hazard, label: "No public map" }],
      };
    },
  );
}

const allOptions = (groups: LayerGroup[]) => groups.flatMap((group) => group.options);

/** Whether an option has something to show: grids and flood maps can still say why they don't. */
export const selectable = (option: LayerOption) => option.kind !== "none";

/** The wanted layer if it's listed, else the first flood map with data, else the first option. */
export function pickLayer(groups: LayerGroup[], wanted: string | null): LayerOption | null {
  const options = allOptions(groups).filter(selectable);
  return (
    options.find((option) => option.id === wanted) ??
    options.find((option) => option.kind === "flood" && option.layer.available) ??
    options.find((option) => option.kind === "flood") ??
    options[0] ??
    null
  );
}
