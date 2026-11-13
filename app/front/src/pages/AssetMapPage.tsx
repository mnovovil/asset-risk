import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError, getAsset, type AssetDetail } from "@/api/client";
import { AssetHazardMap } from "@/components/dashboard/AssetHazardMap";
import { parseAssetMapView, parseRowNum } from "@/lib/assetMapRoute";
import { pairLabel } from "@/lib/dashboard";
import { assetLabel } from "@/lib/format";
import { sortHazards } from "@/lib/hazards";

const TYPE_SOURCES: Record<string, string> = {
  class: "from its Overture class",
  subtype: "from its Overture subtype",
  assumed: "assumed, as Overture has no usable type here",
};

/** One asset's hazard map on a page of its own, opened from the asset panel in a new tab. */
export function AssetMapPage() {
  const { runId = "", rowNum: rowText } = useParams();
  const [params] = useSearchParams();
  const rowNum = parseRowNum(rowText);
  const view = parseAssetMapView(params);
  const complete = rowNum !== null && view !== null;
  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!complete) return;
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
  }, [runId, rowNum, complete]);

  useEffect(() => {
    if (asset) document.title = `${assetLabel(asset)} hazard map · Asset Risk`;
  }, [asset]);

  const back = (
    <p>
      <Link to={`/runs/${encodeURIComponent(runId)}`}>← Back to the portfolio</Link>
    </p>
  );

  if (rowNum === null || !view) {
    return (
      <section>
        {back}
        <p className="notice notice-error" role="alert">
          This link to a hazard map is incomplete.
        </p>
      </section>
    );
  }

  const { pair } = view;
  const matches = (item: { scenario: string; year: number | null }) =>
    item.scenario === pair.scenario && item.year === pair.year;
  const hazards = asset
    ? sortHazards([
        ...asset.impacts.filter(matches).map((i) => i.hazard),
        ...asset.scores.filter(matches).map((s) => s.hazard),
      ])
    : [];

  return (
    <section aria-labelledby="asset-map-heading">
      {back}
      <h1 id="asset-map-heading">{asset ? `${assetLabel(asset)} hazard map` : "Hazard map"}</h1>
      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!asset && !error && <p className="muted">Loading…</p>}
      {asset && (
        <>
          <p className="muted">
            {pairLabel(pair)}
            {asset.lat !== null && asset.lon !== null && ` · ${asset.lat}, ${asset.lon}`}
            {asset.physrisk_type &&
              ` · ${asset.physrisk_type}, ${TYPE_SOURCES[asset.type_source ?? ""] ?? "type not decided"}`}
          </p>
          {!asset.assessable || asset.lat === null || asset.lon === null ? (
            <p className="notice notice-warning">
              This asset wasn't assessed, so it has no hazard map.
            </p>
          ) : (
            <AssetHazardMap
              runId={runId}
              rowNum={rowNum}
              pair={pair}
              lat={asset.lat}
              lon={asset.lon}
              hazards={hazards}
              initialLayer={view.layer}
              initialHistorical={view.historical}
              variant="page"
            />
          )}
        </>
      )}
    </section>
  );
}
