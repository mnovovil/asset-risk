import { useEffect, useState } from "react";

import {
  ApiError,
  type AssetDetail,
  type FloodZoneDefinition,
  type FloodZoneDefinitions,
} from "@/api/client";
import { loadFloodZoneDefinitions, sfhaText, subtypeText } from "@/lib/floodZones";

const MAP_SERVICE_CENTER = "https://msc.fema.gov/portal/search";

function Sources({ sources }: { sources: FloodZoneDefinition["sources"] }) {
  if (sources.length === 0) return null;
  return (
    <p className="panel-note">
      Sources:{" "}
      {sources.map((source, index) => (
        <span key={source.url}>
          {index > 0 && ", "}
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.title}
          </a>
        </span>
      ))}
    </p>
  );
}

function AllZones({ definitions }: { definitions: FloodZoneDefinitions }) {
  const insurance = new Map(definitions.insurance.map((rule) => [rule.key, rule.label]));
  return (
    <div className="table-scroll">
      <table aria-label="All FEMA flood zones">
        <thead>
          <tr>
            <th scope="col">Zone</th>
            <th scope="col">Chance each year</th>
            <th scope="col">High-risk area (SFHA)</th>
            <th scope="col">Flood insurance</th>
            <th scope="col">What it means</th>
          </tr>
        </thead>
        <tbody>
          {definitions.zones.map((zone) => (
            <tr key={zone.key}>
              <th scope="row">{zone.label}</th>
              <td>{zone.annual_chance}</td>
              <td>{zone.sfha === null ? "–" : zone.sfha ? "Yes" : "No"}</td>
              <td>{insurance.get(zone.insurance) ?? zone.insurance}</td>
              <td>{zone.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const unique = (sources: FloodZoneDefinition["sources"]) =>
  sources.filter((source, index) => sources.findIndex((s) => s.url === source.url) === index);

function measure(value: number, unit: string | null, datum?: string | null): string {
  return [String(value), unit, datum ? `(${datum})` : null].filter(Boolean).join(" ");
}

/** The FEMA flood zone at an asset's point, and what that zone means. */
export function FloodZone({ asset }: { asset: AssetDetail }) {
  const [definitions, setDefinitions] = useState<FloodZoneDefinitions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    loadFloodZoneDefinitions()
      .then((loaded) => {
        if (current) setDefinitions(loaded);
      })
      .catch((e: unknown) => {
        if (!current) return;
        setError(e instanceof ApiError ? e.message : "The zone explanations couldn't be loaded.");
      });
    return () => {
      current = false;
    };
  }, []);

  const zone = definitions?.zones.find((z) => z.key === asset.fema_zone_key) ?? null;
  const status = definitions?.statuses.find((s) => s.key === asset.fema_status) ?? null;
  const insurance = definitions?.insurance.find((rule) => rule.key === zone?.insurance) ?? null;
  const mapped = asset.fema_status === "mapped";
  const zoneLabel = zone?.label ?? asset.fema_zone_key ?? asset.fema_zone ?? "Unknown zone";

  return (
    <>
      <h3>FEMA flood zone</h3>
      {mapped ? (
        <>
          {asset.fema_conflict && (
            <p className="notice notice-warning">
              {asset.fema_matches} FEMA map areas overlap here and disagree. The highest-risk one is
              shown.
            </p>
          )}
          <dl>
            <dt>Zone</dt>
            <dd>{zoneLabel}</dd>
            {asset.fema_zone_subtype && (
              <>
                <dt>Subtype</dt>
                <dd>{subtypeText(asset.fema_zone_subtype)}</dd>
              </>
            )}
            {zone && (
              <>
                <dt>Chance each year</dt>
                <dd>{zone.annual_chance}</dd>
              </>
            )}
            <dt>High-risk area (SFHA)</dt>
            <dd>{sfhaText(asset.in_sfha)}</dd>
            {insurance && (
              <>
                <dt>Flood insurance</dt>
                <dd>{insurance.label}</dd>
              </>
            )}
            <dt>Base flood elevation</dt>
            <dd>
              {asset.base_flood_elevation === null
                ? "Not recorded"
                : measure(
                    asset.base_flood_elevation,
                    asset.base_flood_elevation_unit,
                    asset.base_flood_elevation_datum,
                  )}
            </dd>
            {asset.fema_depth !== null && (
              <>
                <dt>Flood depth</dt>
                <dd>{measure(asset.fema_depth, asset.fema_depth_unit)}</dd>
              </>
            )}
            <dt>FEMA map</dt>
            <dd>
              {asset.fema_dfirm_id ?? "–"}
              {asset.fema_map_as_of && `, data as of ${asset.fema_map_as_of}`}
            </dd>
          </dl>
          {zone && zone.sfha !== null && asset.in_sfha !== null && zone.sfha !== asset.in_sfha && (
            <p className="panel-note">
              FEMA's data marks this map area as {asset.in_sfha ? "inside" : "outside"} the high-risk
              area, which is unusual for {zone.label}.
            </p>
          )}
          {asset.base_flood_elevation === null && zone?.sfha && (
            <p className="panel-note">
              No elevation is stored for this map area. FEMA often draws base flood elevations as
              lines along a river, which this data doesn't include, so it may still have one.
            </p>
          )}
        </>
      ) : (
        <p>
          <strong>{status?.label ?? asset.fema_status}</strong>
          {status && `: ${status.summary}`}
        </p>
      )}
      {error && <p className="notice notice-error">{error}</p>}
      {definitions && (
        <details className="twin">
          <summary>{zone ? `What does ${zone.label} mean?` : "What do FEMA flood zones mean?"}</summary>
          {zone && (
            <>
              <p>{zone.summary}</p>
              {insurance && (
                <p>
                  <strong>Flood insurance: {insurance.label.toLowerCase()}.</strong> {insurance.text}
                </p>
              )}
              <Sources sources={unique([...zone.sources, ...(insurance?.sources ?? [])])} />
            </>
          )}
          {zone ? (
            <details>
              <summary>All FEMA flood zones</summary>
              <AllZones definitions={definitions} />
            </details>
          ) : (
            <AllZones definitions={definitions} />
          )}
        </details>
      )}
      <p className="panel-note">
        Not an official flood zone determination. Check the address on{" "}
        <a href={MAP_SERVICE_CENTER} target="_blank" rel="noreferrer">
          FEMA's Flood Map Service Center
        </a>
        .
      </p>
    </>
  );
}
