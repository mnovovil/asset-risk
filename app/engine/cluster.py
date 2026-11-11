"""Group assets into spatial clusters with DBSCAN, for the map's risk-concentration bubbles.

Clusters depend only on where assets are, so they're found once per run. Their colour depends on the
scenario, year and hazard, and is worked out by the dashboard from each member's results.
"""

from __future__ import annotations

import numpy as np

from engine.settings import Settings
from engine.store import Run

EARTH_RADIUS_KM = 6371.0088  # mean radius, as haversine distances in radians are scaled by it


def cluster(run: Run, settings: Settings) -> int:
    """Store each clustered asset's cluster in asset_clusters and return how many clusters exist.

    Points DBSCAN calls noise get no row, so a portfolio with no dense group has no rows at all.
    """
    # Imported here because it takes a moment, and only this needs it.
    from sklearn.cluster import DBSCAN

    with run.connect() as con:
        # Input order (row_num) makes the assignment of border points deterministic.
        rows = con.execute(
            "SELECT row_num, lat, lon FROM assets "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL AND match_type <> 'invalid' "
            "AND abs(lat) <= 90 AND abs(lon) <= 180 ORDER BY row_num"
        ).fetchall()
        con.execute("DELETE FROM asset_clusters")
        if len(rows) < settings.cluster_min_samples:
            return 0
        row_nums = [row_num for row_num, _, _ in rows]
        coordinates = np.radians([[lat, lon] for _, lat, lon in rows])  # haversine wants (lat, lon)
        labels = DBSCAN(
            eps=settings.cluster_eps_km / EARTH_RADIUS_KM,
            min_samples=settings.cluster_min_samples,
            metric="haversine",
            algorithm="ball_tree",
        ).fit_predict(coordinates)
        members = [
            (row_num, int(label))
            for row_num, label in zip(row_nums, labels, strict=True)
            if label >= 0
        ]
        if members:
            con.executemany(
                "INSERT INTO asset_clusters (row_num, cluster_id) VALUES (?, ?)", members
            )
        return len({label for _, label in members})
