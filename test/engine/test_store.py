import csv
import re
from pathlib import Path

import pytest

from engine.geolocation import locate
from engine.ingest import read_portfolio
from engine.store import create_run, load_assets

COLUMNS = (
    "id,lat,lon,match_type,distance_m,building_id,name,class,subtype,height,num_floors,geometry_wkt"
).split(",")


def write_output(run, *rows):
    with open(run.geolocated_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def row(id="a", lat="1.5", lon="2.5", match_type="intersects", **fields):
    values = {"id": id, "lat": lat, "lon": lon, "match_type": match_type} | fields
    return [values.get(c, "") for c in COLUMNS]


def fetch(run, sql):
    with run.connect() as con:
        return con.execute(sql).fetchall()


def test_run_folder_name_is_a_uuid(tmp_path):
    run = create_run(tmp_path, 1, "../../etc/passwd")
    assert re.fullmatch(r"[0-9a-f-]{36}", run.directory.name)
    assert run.directory.parent == tmp_path / "runs"
    assert fetch(run, "SELECT source_name, total_rows FROM runs") == [("../../etc/passwd", 1)]


def test_runs_do_not_share_a_folder(tmp_path):
    assert create_run(tmp_path, 1).directory != create_run(tmp_path, 1).directory


def test_loads_typed_values(tmp_path):
    run = create_run(tmp_path, 1)
    write_output(
        run,
        row(
            distance_m="12.5",
            building_id="b1",
            name="Casa",
            height="6.0",
            num_floors="2",
            **{"class": "house", "subtype": "residential"},
            geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))",
        ),
    )
    assert load_assets(run) == 1
    assert fetch(run, "SELECT * FROM assets") == [
        (
            1,
            "a",
            1.5,
            2.5,
            "intersects",
            12.5,
            "b1",
            "Casa",
            "house",
            "residential",
            6.0,
            2,
            "POLYGON ((0 0, 1 0, 1 1, 0 0))",
        )
    ]


def test_keeps_input_order_and_bad_rows(tmp_path):
    run = create_run(tmp_path, 3)
    write_output(
        run,
        row(id="z"),
        row(id="", lat="", lon="", match_type="invalid"),
        row(id="y", lat="abc", match_type="invalid"),
    )
    load_assets(run)
    assert fetch(run, "SELECT row_num, asset_id, lat FROM assets ORDER BY row_num") == [
        (1, "z", 1.5),
        (2, None, None),
        (3, "y", None),
    ]


def test_awkward_text_survives_the_csv(tmp_path):
    run = create_run(tmp_path, 2)
    write_output(
        run,
        row(id='a,"b"', name='Café "Sol", Madrid'),
        row(id="line", name="two\nlines"),
    )
    load_assets(run)
    assert fetch(run, "SELECT asset_id, name FROM assets ORDER BY row_num") == [
        ('a,"b"', 'Café "Sol", Madrid'),
        ("line", "two\nlines"),
    ]


def test_very_long_footprint_loads(tmp_path):
    run = create_run(tmp_path, 1)
    wkt = "POLYGON ((" + ", ".join(["1.123456789 2.123456789"] * 200_000) + "))"
    write_output(run, row(geometry_wkt=wkt))
    load_assets(run)
    assert fetch(run, "SELECT length(geometry_wkt) FROM assets") == [(len(wkt),)]


def test_row_count_mismatch_is_an_error(tmp_path):
    run = create_run(tmp_path, 2)
    write_output(run, row())
    with pytest.raises(ValueError, match="expected 2"):
        load_assets(run)


def test_end_to_end_from_csv_to_table(local_settings, coords_csv):
    points = read_portfolio(coords_csv, 100)
    run = create_run(local_settings.data_dir, len(points), Path(coords_csv).name)
    locate(points, run.geolocated_csv, local_settings)
    assert load_assets(run) == len(points)
    assert fetch(run, "SELECT asset_id, match_type, class FROM assets WHERE row_num = 1") == [
        ("p1", "intersects", "house")
    ]
    assert fetch(run, "SELECT count(*) FROM assets WHERE match_type = 'invalid'") == [(4,)]
