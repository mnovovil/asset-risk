import csv
import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from engine import geolocation
from engine.geolocation import GeolocationError, _module, locate
from engine.ingest import read_portfolio

ENGINE = Path(geolocation.__file__).parent


def test_locates_points_with_the_library(local_settings, coords_csv, tmp_path):
    points = read_portfolio(coords_csv, 100)
    output = tmp_path / "out.csv"
    counts = locate(points, output, local_settings)

    assert counts == {"intersects": 3, "nearest": 1, "none": 1, "invalid": 4}
    with open(output, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == [p[0] or "" for p in points]
    assert rows[0]["class"] == "house"
    assert rows[0]["subtype"] == "residential"
    assert rows[0]["geometry_wkt"].startswith("POLYGON")


def test_reports_progress_up_to_the_total(local_settings, coords_csv, tmp_path):
    points = read_portfolio(coords_csv, 100)
    seen = []
    locate(points, tmp_path / "out.csv", local_settings, lambda done, total: seen.append(done))
    assert seen == sorted(seen)
    assert seen[-1] == len(points)
    assert len(seen) == 3  # 9 rows in batches of 3


def test_progress_counts_a_name_with_a_newline_once(tmp_path):
    with open(tmp_path / "out.csv", "w", newline="") as f:
        seen = []
        counting = geolocation._CountingFile(f, 1, lambda done, total: seen.append((done, total)))
        writer = csv.writer(counting)
        writer.writerow(["id", "name"])
        writer.writerow(["a", "two\nlines"])
        counting.flush()
    assert seen == [(1, 1)]


def test_missing_config_is_explained(settings, tmp_path):
    with pytest.raises(GeolocationError, match="not found"):
        locate([("a", "1", "2")], tmp_path / "out.csv", settings)


def test_library_failure_is_wrapped(local_settings, tmp_path):
    (tmp_path / "bad.json").write_text(
        local_settings.geolocate_config.read_text().replace(".parquet", ".missing")
    )
    bad = replace(local_settings, geolocate_config=tmp_path / "bad.json")
    with pytest.raises(GeolocationError, match="geolocate failed"):
        locate([("a", "40.4", "-3.7")], tmp_path / "out.csv", bad)


def test_missing_submodule_names_the_fix(tmp_path):
    with pytest.raises(GeolocationError, match="git submodule update --init"):
        _module("geolocate", tmp_path)


def test_no_module_name_clash():
    importlib.import_module("engine.settings")
    for name in ("config", "db", "match", "geolocate"):
        assert Path(_module(name).__file__).parent == geolocation.GEOLOCATE_SRC
        assert not (ENGINE / f"{name}.py").exists()


def test_only_the_adapter_touches_the_vendored_path():
    for path in ENGINE.glob("*.py"):
        if path.name != "geolocation.py":
            assert "vendor" not in path.read_text(), path


@pytest.mark.s3
def test_live_overture(tmp_path):
    from engine.settings import load_settings

    path = tmp_path / "portfolio.csv"
    path.write_text(
        "id,lat,lon\nempire,40.7484,-73.9857\nbigben,51.5007,-0.1246\nocean,0.0,-30.0\n"
    )
    counts = locate(read_portfolio(path, 10), tmp_path / "out.csv", load_settings())
    assert counts["invalid"] == 0
    assert counts["none"] == 1
    assert counts["intersects"] + counts["nearest"] == 2
