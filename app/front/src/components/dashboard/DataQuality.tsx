import type { Asset, Summary, TrajectoryPoint } from "@/api/client";
import { assumedShare } from "@/lib/dashboard";
import { assetLabel, count, joinList, plural, scenarioLabel } from "@/lib/format";
import { hazardLabel } from "@/lib/hazards";

const EXCLUSION_LABELS: Record<string, string> = {
  invalid: "Invalid (missing id, or bad latitude or longitude)",
  off_land: "Off land (no building and no country nearby)",
  no_curve: "No damage model for this building type and region",
};
const MAX_LISTED_EXCLUSIONS = 100;
/** Past this share, the assumption shapes the results more than the data does. */
const ASSUMED_WARNING_SHARE = 0.5;

interface DataQualityProps {
  summary: Summary;
  assets: Asset[];
  trajectory: TrajectoryPoint[];
  missing: string[];
  defaultType: string | null;
  onSelect: (rowNum: number) => void;
}

export function DataQuality({
  summary,
  assets,
  trajectory,
  missing,
  defaultType,
  onSelect,
}: DataQualityProps) {
  const excluded = assets.filter((asset) => asset.exclusion_reason);
  const emptyScenarios = [
    ...new Set(trajectory.filter((p) => p.year !== null && p.assets === 0).map((p) => p.scenario)),
  ];
  const assumed = assumedShare(summary.assessable, summary.assumed_type);

  return (
    <section className="panel" aria-labelledby="quality-heading">
      <h2 id="quality-heading">How far to trust these results</h2>
      {assumed > ASSUMED_WARNING_SHARE && (
        <p className="notice notice-warning">
          The building type was assumed for {Math.round(assumed * 100)}% of assets
          {defaultType && `, using ${defaultType}`}. The type changes the flood damage model, so
          these results can move materially if the assumption is wrong.
        </p>
      )}
      <div className="data-quality">
        <div>
          <h3>This portfolio</h3>
          <ul>
            <li>{plural(summary.assumed_type, "asset")} with an assumed building type</li>
            <li>
              {plural(summary.nearest_match, "asset")} matched to a nearby building, which may be a
              neighbour
            </li>
            <li>{plural(summary.no_building, "asset")} with no building found within range</li>
            <li>{plural(summary.global_curve, "asset")} using a global, not regional, damage model</li>
            {summary.failed_assets > 0 && (
              <li>{plural(summary.failed_assets, "asset")} missing results after a failed request</li>
            )}
            {summary.exclusions.map((exclusion) => (
              <li key={exclusion.reason}>
                {count(exclusion.assets)} excluded:{" "}
                {EXCLUSION_LABELS[exclusion.reason] ?? exclusion.reason}
              </li>
            ))}
            {missing.length > 0 && (
              <li>Not available for this scenario: {joinList(missing.map(hazardLabel))}</li>
            )}
            {emptyScenarios.length > 0 && (
              <li>
                No results at all for {joinList(emptyScenarios.map(scenarioLabel))}. physrisk's data
                doesn't cover {emptyScenarios.length === 1 ? "it" : "them"}.
              </li>
            )}
          </ul>
          {excluded.length > 0 && (
            <details className="twin">
              <summary>Show excluded assets</summary>
              <ul>
                {excluded.slice(0, MAX_LISTED_EXCLUSIONS).map((asset) => (
                  <li key={asset.row_num}>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onSelect(asset.row_num)}
                    >
                      {assetLabel(asset)}
                    </button>
                  </li>
                ))}
              </ul>
              {excluded.length > MAX_LISTED_EXCLUSIONS && (
                <p className="muted">
                  Showing the first {MAX_LISTED_EXCLUSIONS}. The CSV download lists them all.
                </p>
              )}
            </details>
          )}
        </div>
        <div>
          <h3>The model</h3>
          <ul>
            <li>This is for screening many sites, not for decisions about one site.</li>
            <li>Hazard data has pixels of about 1 km, so results depend on exact coordinates.</li>
            <li>
              Flood results assume a global estimate of flood protection, and a site's real defences
              may be very different.
            </li>
            <li>River flood comes from a single climate model.</li>
            <li>
              Wind means tropical cyclones only. Zero wind doesn't mean no wind risk, for example
              from European windstorms.
            </li>
            <li>Results are a share of asset value, as asset values aren't known here.</li>
          </ul>
        </div>
      </div>
    </section>
  );
}
