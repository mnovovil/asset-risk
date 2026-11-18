/**
 * A still picture of a portfolio's "Where the risk is" map, as the dashboard opens it.
 *
 * Each thumbnail draws one map off screen with `snapshotMap`, which keeps only one such map at a
 * time, and shows the saved image.
 */

import { useEffect, useState } from "react";

import { type Snapshot, snapshotMap } from "@/components/mapSnapshot";
import { usePrefersDark } from "@/hooks/useColorScheme";
import { pointRing } from "@/lib/mapStyle";
import { thumbnailFeatures } from "@/lib/thumbnail";

import type { AssetTotal, Cluster, MapPoint } from "@/api/client";

// The size drawn off screen, at the card's 16:9. The card scales the image to fit.
const WIDTH_PX = 640;
const HEIGHT_PX = 360;

type State = { kind: "waiting" } | { kind: "ready"; snapshot: Snapshot } | { kind: "unavailable" };

const cache = new Map<string, Snapshot>();

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
    snapshotMap(thumbnail, {
      width: WIDTH_PX,
      height: HEIGHT_PX,
      dark,
      cancelled: () => cancelled,
    })
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
