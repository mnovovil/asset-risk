import { useEffect, useRef, useState } from "react";

import { ApiError, getAsset, type AssetDetail, type Pair } from "@/api/client";
import { isBaseline, pairLabel, SCORE_NOTES, scoreKind } from "@/lib/dashboard";
import { assetLabel, percent } from "@/lib/format";
import { hazardLabel, sortHazards } from "@/lib/hazards";

import { AssetChart } from "./AssetChart";
import { AssetHazardMap } from "./AssetHazardMap";
import { FloodZone } from "./FloodZone";

function matchText(asset: AssetDetail): string {
  switch (asset.match_type) {
    case "intersects":
      return "The point is inside this building";
    case "nearest":
      return `Nearest building, ${asset.distance_m ?? "?"} m away. It may be a neighbour.`;
    case "none":
      return "No building found within range";
    default:
      return "The row is invalid";
  }
}

function typeText(asset: AssetDetail): string {
  switch (asset.type_source) {
    case "class":
      return `From the Overture class "${asset.class}"`;
    case "subtype":
      return `From the Overture subtype "${asset.subtype}"`;
    case "assumed":
      return "Assumed: Overture has no usable type here. Results can move if this is wrong.";
    default:
      return "Not assessed";
  }
}

const EXCLUSIONS: Record<string, string> = {
  invalid: "Excluded: the id, latitude or longitude is missing or invalid.",
  off_land: "Excluded: no building found, and not near any country.",
  no_curve: "Excluded: physrisk has no damage model for this building type and region.",
};

interface AssetPanelProps {
  runId: string;
  rowNum: number;
  pair: Pair;
  /** The run's scenarios, so the chart can name one with no results for a hazard. */
  scenarios: string[];
  onClose: () => void;
}

export function AssetPanel({ runId, rowNum, pair, scenarios, onClose }: AssetPanelProps) {
  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    setAsset(null);
    setError(null);
    getAsset(runId, rowNum, controller.signal)
      .then(setAsset)
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "This asset couldn't be loaded.");
      });
    return () => controller.abort();
  }, [runId, rowNum]);

  const matches = (item: { scenario: string; year: number | null }) =>
    item.scenario === pair.scenario && item.year === pair.year;
  const impacts = asset?.impacts.filter(matches) ?? [];
  const scores = asset?.scores.filter(matches) ?? [];
  const hazards = sortHazards([...impacts.map((i) => i.hazard), ...scores.map((s) => s.hazard)]);
  // physrisk scores scenarios only, so the baseline's table has no score column.
  const baseline = isBaseline(pair);

  return (
    <aside className="asset-panel" role="dialog" aria-label="Asset details">
      <div className="asset-panel-header">
        <h2>{asset ? assetLabel(asset) : "Asset"}</h2>
        <button ref={closeButton} type="button" className="button" onClick={onClose}>
          Close
        </button>
      </div>
      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!asset && !error && <p className="muted">Loading…</p>}
      {asset && (
        <>
          {asset.exclusion_reason && (
            <p className="notice notice-warning">
              {EXCLUSIONS[asset.exclusion_reason] ?? `Excluded: ${asset.exclusion_reason}`}
            </p>
          )}
          <h3>Building</h3>
          <dl>
            <dt>Match</dt>
            <dd>{matchText(asset)}</dd>
            <dt>Name</dt>
            <dd>{asset.name ?? "–"}</dd>
            <dt>Class</dt>
            <dd>{asset.class ?? "–"}</dd>
            <dt>Subtype</dt>
            <dd>{asset.subtype ?? "–"}</dd>
            <dt>Height</dt>
            <dd>{asset.height === null ? "–" : `${asset.height} m`}</dd>
            <dt>Floors</dt>
            <dd>{asset.num_floors ?? "–"}</dd>
            <dt>Location</dt>
            <dd>
              {asset.lat ?? "–"}, {asset.lon ?? "–"}
            </dd>
          </dl>
          <p className="panel-note">Height and floors are shown for context. They don't affect the results.</p>
          <h3>How it was modelled</h3>
          <dl>
            <dt>Type</dt>
            <dd>{asset.physrisk_type ?? "–"}</dd>
            <dt>Decided by</dt>
            <dd>{typeText(asset)}</dd>
            <dt>Region</dt>
            <dd>
              {asset.physrisk_location ?? "–"}
              {asset.location_fallback &&
                ` (physrisk has no ${asset.region} model for this type, so this uses its global one)`}
            </dd>
          </dl>
          <FloodZone asset={asset} />
          {asset.assessable && (
            <>
              <h3>
                Results for {pairLabel(pair)}
              </h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Hazard</th>
                      <th scope="col">Annual loss</th>
                      {!baseline && <th scope="col">Score</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {hazards.map((hazard) => {
                      const impact = impacts.find((i) => i.hazard === hazard);
                      const score = scores.find((s) => s.hazard === hazard);
                      const kind = score ? scoreKind(score.score) : null;
                      return (
                        <tr key={hazard}>
                          <th scope="row">{hazardLabel(hazard)}</th>
                          <td>{impact ? percent(impact.aal) : "–"}</td>
                          {!baseline && (
                            <td className={kind === "scored" ? "" : "score-none"}>
                              {kind === "scored"
                                ? score?.label
                                : kind
                                  ? SCORE_NOTES[kind]
                                  : "Not returned"}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <h3>Over time</h3>
              <AssetChart asset={asset} pair={pair} scenarios={scenarios} />
              {asset.lat !== null && asset.lon !== null && (
                <>
                  <h3>Hazard maps</h3>
                  <AssetHazardMap
                    runId={runId}
                    rowNum={rowNum}
                    pair={pair}
                    lat={asset.lat}
                    lon={asset.lon}
                    hazards={hazards}
                  />
                </>
              )}
            </>
          )}
        </>
      )}
    </aside>
  );
}
