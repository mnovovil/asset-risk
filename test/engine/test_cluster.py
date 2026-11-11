from dataclasses import replace

import pytest

from engine.cluster import cluster
from engine.store import create_run

KM_PER_DEGREE_LAT = 111.195  # at the mean Earth radius


def make_run(tmp_path, points):
    """points: (lat, lon) or (lat, lon, match_type)."""
    run = create_run(tmp_path, len(points))
    with run.connect() as con:
        con.executemany(
            "INSERT INTO assets (row_num, asset_id, lat, lon, match_type) VALUES (?, ?, ?, ?, ?)",
            [
                (i, f"a{i}", p[0], p[1], p[2] if len(p) > 2 else "intersects")
                for i, p in enumerate(points)
            ],
        )
    return run


def clusters_of(run):
    with run.connect() as con:
        return dict(con.execute("SELECT row_num, cluster_id FROM asset_clusters").fetchall())


def group(lat, lon, n=5, step=0.01):
    return [(lat + i * step, lon) for i in range(n)]


@pytest.fixture
def cluster_settings(settings):
    return replace(settings, cluster_eps_km=50.0, cluster_min_samples=3)


def test_dense_groups_cluster_and_noise_is_left_out(tmp_path, cluster_settings):
    madrid, tokyo = group(40.4, -3.7), group(35.7, 139.7)
    lone = [(-33.9, 151.2), (51.5, -0.1)]
    run = make_run(tmp_path, madrid + lone + tokyo)
    assert cluster(run, cluster_settings) == 2
    found = clusters_of(run)
    assert set(found) == set(range(5)) | set(range(7, 12))
    assert len({found[i] for i in range(5)}) == 1
    assert len({found[i] for i in range(7, 12)}) == 1
    assert found[0] != found[7]


def test_scattered_portfolio_has_no_clusters(tmp_path, cluster_settings):
    worldwide = [(lat, lon) for lat in (-40, 0, 40) for lon in (-120, 0, 120)]
    run = make_run(tmp_path, worldwide)
    assert cluster(run, cluster_settings) == 0
    assert clusters_of(run) == {}


def test_too_few_points_has_no_clusters(tmp_path, cluster_settings):
    run = make_run(tmp_path, [(40.0, -3.0), (40.0, -3.0)])
    assert cluster(run, cluster_settings) == 0
    assert clusters_of(run) == {}


def test_invalid_and_missing_coordinates_are_never_clustered(tmp_path, cluster_settings):
    run = make_run(
        tmp_path,
        [*group(40.4, -3.7, n=3), (40.4, -3.7, "invalid"), (None, None, "invalid"), (95, 1)],
    )
    assert cluster(run, cluster_settings) == 1
    assert set(clusters_of(run)) == {0, 1, 2}


@pytest.mark.parametrize(("eps", "clustered"), [(50.0, True), (30.0, False)])
def test_distance_is_great_circle_km(tmp_path, cluster_settings, eps, clustered):
    # Two points 40 km apart, north to south, form a cluster only when eps is more than 40 km.
    run = make_run(tmp_path, [(10.0, 0.0), (10.0 + 40 / KM_PER_DEGREE_LAT, 0.0)])
    settings = replace(cluster_settings, cluster_eps_km=eps, cluster_min_samples=2)
    assert cluster(run, settings) == (1 if clustered else 0)


def test_cluster_across_the_antimeridian(tmp_path, cluster_settings):
    run = make_run(tmp_path, [(0.0, 179.9), (0.0, -179.9), (0.0, 179.95)])
    assert cluster(run, cluster_settings) == 1
    assert set(clusters_of(run)) == {0, 1, 2}


def test_rerunning_gives_the_same_clusters(tmp_path, cluster_settings):
    run = make_run(tmp_path, group(40.4, -3.7) + group(35.7, 139.7) + [(0.0, 0.0)])
    cluster(run, cluster_settings)
    first = clusters_of(run)
    cluster(run, cluster_settings)
    assert clusters_of(run) == first
