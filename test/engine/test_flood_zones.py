"""The FEMA flood zone pipeline stage, on a small database built from synthetic polygons."""

import json
import logging
import math
import re
from dataclasses import replace
from datetime import date

import pytest

from engine.classify import COUNTRIES
from engine.flood_zone_data import ZONES_FILE, build, definitions, known_zones, zone_ranks
from engine.flood_zones import SQL_DIR, TILE_DEG, US_COUNTRIES, map_flood_zones
from engine.store import create_run

USA = "United States of America"
AS_OF = date(2026, 11, 13)


def square(west, south, east, north):
    return (
        f"POLYGON(({west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}))"
    )


POLYGONS = [
    # Galveston: a VE polygon inside an OPEN WATER one from another study, as in FEMA's data.
    {
        "id": "ve",
        "zone": "VE",
        "wkt": square(-94.80, 29.28, -94.78, 29.30),
        "bfe": 19.0,
        "datum": "NAVD88",
        "dfirm": "485469",
    },
    {"id": "ow", "zone": "OPEN WATER", "wkt": square(-94.81, 29.27, -94.77, 29.31), "sfha": "F"},
    # Two AE neighbours sharing the line lon = -94.70.
    {"id": "w", "zone": "AE", "wkt": square(-94.72, 29.28, -94.70, 29.30), "bfe": 12.0},
    {"id": "e", "zone": "AE", "wkt": square(-94.70, 29.28, -94.68, 29.30), "bfe": 11.0},
    {
        "id": "levee",
        "zone": "X",
        "subtype": "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE",
        "wkt": square(-90.10, 29.90, -90.00, 30.00),
        "sfha": "F",
    },
    {
        "id": "minimal",
        "zone": "X",
        "subtype": "area of minimal flood hazard ",
        "wkt": square(-105.0, 39.7, -104.9, 39.8),
        "sfha": "F",
    },
    {
        "id": "x",
        "zone": "X",
        "subtype": "<Null>",
        "wkt": square(-100.0, 40.0, -99.9, 40.1),
        "sfha": "F",
    },
    {
        "id": "ao",
        "zone": "AO",
        "wkt": square(-110.0, 33.0, -109.9, 33.1),
        "sfha": "U",
        "bfe": -8888.0,
        "depth": 2.0,
        "unit": " FEET",
    },
    # The same zone and elevation from two studies: DFIRM_ID decides.
    {"id": "b", "zone": "AE", "wkt": square(-80.0, 26.0, -79.9, 26.1), "bfe": 10.0, "dfirm": "B"},
    {"id": "a", "zone": "AE", "wkt": square(-80.0, 26.0, -79.9, 26.1), "bfe": 10.0, "dfirm": "A"},
    # A polygon saying it's in the SFHA beats a higher elevation that says it isn't.
    {"id": "f", "zone": "AE", "wkt": square(-81.0, 27.0, -80.9, 27.1), "bfe": 20.0, "sfha": "F"},
    {"id": "t", "zone": "AE", "wkt": square(-81.0, 27.0, -80.9, 27.1), "bfe": 10.0},
    {"id": "guam", "zone": "A", "wkt": square(144.7, 13.4, 144.8, 13.5)},
    {
        "id": "samoa",
        "zone": "VE",
        "wkt": square(-170.75, -14.35, -170.65, -14.25),
        "bfe": 10.0,
        "datum": "<NULL>",
    },
]

# (asset id, lon, lat, country)
ASSETS = [
    ("galveston", -94.79, 29.29, USA),
    ("edge", -94.70, 29.29, USA),
    ("levee", -90.05, 29.95, USA),
    ("minimal", -104.95, 39.75, USA),
    ("x", -99.95, 40.05, USA),
    ("ao", -109.95, 33.05, USA),
    ("tie", -79.95, 26.05, USA),
    ("sfha", -80.95, 27.05, USA),
    ("guam", 144.75, 13.45, "Guam"),
    ("samoa", -170.7, -14.3, "American Samoa"),
    ("unmapped", -100.5, 35.0, USA),
    ("madrid", -3.7, 40.4, "Spain"),
    ("off_land", -94.79, 29.29, None),  # country unknown: not looked up, even on a polygon
]

COLUMNS = (
    "fema_status, fema_zone, fema_zone_subtype, fema_zone_key, in_sfha, base_flood_elevation, "
    "base_flood_elevation_unit, base_flood_elevation_datum, fema_depth, fema_depth_unit, "
    "fema_dfirm_id, fema_fld_ar_id, fema_matches, fema_conflict"
)


@pytest.fixture
def flood_db(write_flood_source, tmp_path):
    out = tmp_path / "fema" / "flood-zones.duckdb"
    build(write_flood_source(tmp_path / "source.parquet", POLYGONS), out, AS_OF)
    return out


def make_run(tmp_path, assets=ASSETS, invalid=True):
    run = create_run(tmp_path / "data", len(assets) + invalid)
    with run.connect() as con:
        for row_num, (asset_id, lon, lat, country) in enumerate(assets, 1):
            con.execute(
                "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, country) "
                "VALUES (?, ?, ?, ?, 'none', ?)",
                [row_num, asset_id, lat, lon, country],
            )
        if invalid:
            con.execute(
                "INSERT INTO assets (row_num, asset_id, match_type) VALUES (?, NULL, 'invalid')",
                [len(assets) + 1],
            )
    return run


def zones(run) -> dict:
    with run.connect() as con:
        cursor = con.execute(
            f"SELECT coalesce(a.asset_id, 'invalid'), {COLUMNS} FROM assets a "
            "JOIN asset_flood_zones USING (row_num) ORDER BY row_num"
        )
        names = [d[0] for d in cursor.description][1:]
        return {row[0]: dict(zip(names, row[1:], strict=True)) for row in cursor.fetchall()}


@pytest.fixture
def mapped(tmp_path, settings, flood_db):
    run = make_run(tmp_path)
    counts = map_flood_zones(run, replace(settings, flood_zones_db=flood_db))
    return run, counts, zones(run)


def test_every_asset_gets_a_status(mapped):
    _, counts, result = mapped
    assert counts == {"mapped": 10, "not_mapped": 1, "not_us": 2, "not_located": 1}
    assert {k: v["fema_status"] for k, v in result.items()} == {
        **{asset_id: "mapped" for asset_id, *_ in ASSETS[:10]},
        "unmapped": "not_mapped",
        "madrid": "not_us",
        "off_land": "not_us",
        "invalid": "not_located",
    }
    for asset_id in ("unmapped", "madrid", "off_land", "invalid"):
        assert result[asset_id]["fema_zone"] is None
        assert result[asset_id]["fema_matches"] == 0


def test_the_highest_risk_zone_wins_and_the_overlap_shows(mapped):
    galveston = mapped[2]["galveston"]
    assert (galveston["fema_zone"], galveston["fema_zone_key"]) == ("VE", "VE")
    assert (galveston["fema_matches"], galveston["fema_conflict"]) == (2, True)
    assert galveston["fema_dfirm_id"] == "485469"
    assert galveston["in_sfha"] is True
    assert galveston["base_flood_elevation"] == 19.0
    assert galveston["base_flood_elevation_unit"] == "feet"
    assert galveston["base_flood_elevation_datum"] == "NAVD88"


def test_a_point_on_a_shared_edge_matches_both_and_takes_the_higher_elevation(mapped):
    edge = mapped[2]["edge"]
    assert (edge["fema_status"], edge["fema_zone"]) == ("mapped", "AE")
    assert (edge["fema_matches"], edge["fema_conflict"]) == (2, False)
    assert (edge["fema_fld_ar_id"], edge["base_flood_elevation"]) == ("w", 12.0)


def test_ties_are_broken_the_same_way_every_time(mapped):
    assert mapped[2]["tie"]["fema_dfirm_id"] == "A"
    sfha = mapped[2]["sfha"]
    assert (sfha["in_sfha"], sfha["base_flood_elevation"], sfha["fema_fld_ar_id"]) == (
        True,
        10.0,
        "t",
    )


def test_zone_x_keeps_its_shading(mapped):
    result = mapped[2]
    assert result["levee"]["fema_zone_key"] == "X_SHADED"
    assert result["levee"]["fema_zone_subtype"] == "AREA WITH REDUCED FLOOD RISK DUE TO LEVEE"
    # Trimmed and upper-cased before it's read.
    assert result["minimal"]["fema_zone_key"] == "X_UNSHADED"
    assert result["minimal"]["fema_zone_subtype"] == "AREA OF MINIMAL FLOOD HAZARD"
    # "<Null>" is FEMA's text for no subtype, so the shading is unknown.
    assert (result["x"]["fema_zone_key"], result["x"]["fema_zone_subtype"]) == ("X", None)
    for asset_id in ("levee", "minimal", "x"):
        assert result[asset_id]["fema_zone"] == "X"
        assert result[asset_id]["in_sfha"] is False


def test_sentinels_and_unknowns_become_null(mapped):
    ao = mapped[2]["ao"]
    assert ao["fema_zone"] == "AO"
    assert ao["in_sfha"] is None  # SFHA_TF is U
    assert ao["base_flood_elevation"] is None  # -8888
    assert ao["base_flood_elevation_unit"] is None  # no elevation, so no unit
    assert (ao["fema_depth"], ao["fema_depth_unit"]) == (2.0, "feet")
    levee = mapped[2]["levee"]
    assert (levee["base_flood_elevation"], levee["fema_depth"]) == (None, None)  # -9999
    assert mapped[2]["samoa"]["base_flood_elevation_datum"] is None  # "<NULL>"


def test_territories_on_both_sides_of_the_antimeridian(mapped):
    assert mapped[2]["guam"]["fema_zone"] == "A"
    assert mapped[2]["samoa"]["fema_zone"] == "VE"


def test_only_us_points_are_looked_up_one_tile_at_a_time(tmp_path, settings, flood_db):
    calls = []
    run = make_run(tmp_path)
    map_flood_zones(
        run, replace(settings, flood_zones_db=flood_db), lambda d, t: calls.append((d, t))
    )
    us_tiles = {
        (math.floor(lon / TILE_DEG), math.floor(lat / TILE_DEG))
        for _, lon, lat, country in ASSETS
        if country in US_COUNTRIES
    }
    assert calls[-1] == (len(us_tiles), len(us_tiles))

    calls.clear()
    outside = make_run(tmp_path / "outside", [a for a in ASSETS if a[3] not in US_COUNTRIES])
    map_flood_zones(
        outside, replace(settings, flood_zones_db=flood_db), lambda d, t: calls.append((d, t))
    )
    assert calls == []


def test_records_the_data_it_used(mapped):
    run = mapped[0]
    with run.connect() as con:
        assert con.execute(
            "SELECT source_name, source_crs, polygons, as_of FROM flood_zone_source"
        ).fetchall() == [("source.parquet", "OGC:CRS84", len(POLYGONS), AS_OF)]


def test_running_again_replaces_the_rows(tmp_path, settings, flood_db):
    run = make_run(tmp_path)
    configured = replace(settings, flood_zones_db=flood_db)
    map_flood_zones(run, configured)
    map_flood_zones(run, configured)
    with run.connect() as con:
        assert (
            con.execute("SELECT count(*) FROM asset_flood_zones").fetchone()[0] == len(ASSETS) + 1
        )
        assert con.execute("SELECT count(*) FROM flood_zone_source").fetchone()[0] == 1
        # The database is detached again, so nothing else can read it through the run.
        assert "fema" not in {
            name
            for (name,) in con.execute("SELECT database_name FROM duckdb_databases()").fetchall()
        }


def test_without_a_database_us_points_are_unavailable(tmp_path, settings, caplog):
    run = make_run(tmp_path)
    with caplog.at_level(logging.INFO, logger="engine.flood_zones"):
        counts = map_flood_zones(run, replace(settings, flood_zones_db=None))
    assert counts == {"unavailable": 11, "not_us": 2, "not_located": 1}
    assert "No flood_zones_db" in caplog.text
    with run.connect() as con:
        assert con.execute("SELECT count(*) FROM flood_zone_source").fetchone()[0] == 0


@pytest.mark.parametrize("content", [None, "not a database"])
def test_an_unusable_database_is_reported_not_fatal(tmp_path, settings, caplog, content):
    path = tmp_path / "flood-zones.duckdb"
    if content is not None:
        path.write_text(content)
    run = make_run(tmp_path)
    with caplog.at_level(logging.WARNING, logger="engine.flood_zones"):
        counts = map_flood_zones(run, replace(settings, flood_zones_db=path))
    assert counts["unavailable"] == 11
    assert "FEMA flood zones are unavailable" in caplog.text


def test_every_key_the_sql_can_produce_has_a_definition():
    sql = (SQL_DIR / "flood_zones.sql").read_text()
    x_keys = set(re.findall(r"THEN '(X_\w+)'", sql)) | {"X"}
    assert x_keys == {"X", "X_SHADED", "X_UNSHADED"}
    assert set(zone_ranks()) == (known_zones() - {"X"}) | x_keys


def test_us_country_names_exist_in_the_country_data():
    names = {f["properties"]["name"] for f in json.loads(COUNTRIES.read_text())["features"]}
    assert set(US_COUNTRIES) <= names


def test_definitions_are_complete_and_cited():
    result = definitions()
    insurance = {rule["key"] for rule in result["insurance"]}
    assert insurance == {"required", "not_required", "not_applicable"}
    for zone in result["zones"]:
        assert zone["insurance"] in insurance
        assert zone["label"] and zone["summary"] and zone["annual_chance"]
        assert zone["sources"], zone["key"]
        for source in zone["sources"]:
            assert re.match(
                r"https://(www\.)?(fema\.gov|floodsmart\.gov|uscode\.house\.gov)/", source["url"]
            )
        # A zone FEMA counts as an SFHA always needs insurance, and one it doesn't never does.
        if zone["sfha"] is True:
            assert zone["insurance"] == "required"
        if zone["sfha"] is False:
            assert zone["insurance"] == "not_required"
    schema = (SQL_DIR / "schema.sql").read_text()
    allowed = set(
        re.search(r"fema_status IN \(([^)]*)\)", schema)
        .group(1)
        .replace("'", "")
        .replace(" ", "")
        .split(",")
    )
    assert {status["key"] for status in result["statuses"]} == allowed - {"mapped"}
    # Every source the lookup lists is used.
    lookup = json.loads(ZONES_FILE.read_text())
    used = {key for item in lookup["zones"] + lookup["insurance"] for key in item["sources"]}
    assert used == set(lookup["sources"])
