import csv
import json

import pytest

from engine.classify import (
    COUNTRIES,
    TYPE_MAP,
    ClassificationError,
    check_building_types,
    classify,
    valid_curves,
)
from engine.settings import BUILDING_TYPES
from engine.store import create_run

MADRID = (40.4168, -3.7038)
HOUSTON = (29.76, -95.37)
NAIROBI = (-1.2921, 36.8219)
SYDNEY = (-33.8688, 151.2093)
ANTARCTICA = (-80.0, 0.0)
MID_ATLANTIC = (30.0, -40.0)
# Coastal points from the notebook's portfolio, and one just off a coast.
MANILA = (14.60, 120.98)
BARISAL = (22.6588, 90.3373)
OFF_LISBON = (38.70, -9.60)  # about 10 km offshore
WEST_OF_ICELAND = (65.0, -25.5)
EXPECTED_KM = 75.0
# Far from any country in the data; a matched building here proves it isn't open sea.
REMOTE = (-49.0, -30.0)


def add(con, row_num, point, match_type="intersects", class_=None, subtype=None):
    lat, lon = point if point else (None, None)
    con.execute(
        "INSERT INTO assets (row_num, asset_id, lat, lon, match_type, class, subtype) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [row_num, f"a{row_num}", lat, lon, match_type, class_, subtype],
    )


def classify_rows(tmp_path, settings, *rows):
    """Classify rows of (point, kwargs) and return the assets as dicts in order."""
    run = create_run(tmp_path, len(rows))
    with run.connect() as con:
        for i, (point, kwargs) in enumerate(rows, 1):
            add(con, i, point, **kwargs)
    summary = classify(run, settings)
    with run.connect() as con:
        cursor = con.execute("SELECT * FROM assets ORDER BY row_num")
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()], summary


def one(tmp_path, settings, point, **kwargs):
    return classify_rows(tmp_path, settings, (point, kwargs))[0][0]


def test_class_beats_subtype(tmp_path, settings):
    a = one(tmp_path, settings, MADRID, class_="warehouse", subtype="commercial")
    assert (a["physrisk_type"], a["type_source"]) == ("Buildings/Industrial", "class")


def test_subtype_used_when_class_says_nothing(tmp_path, settings):
    a = one(tmp_path, settings, MADRID, class_="roof", subtype="residential")
    assert (a["physrisk_type"], a["type_source"]) == ("Buildings/Residential", "subtype")


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"class_": "roof"}, {"class_": "never_seen"}, {"subtype": "never_seen"}],
)
def test_no_usable_value_is_assumed(tmp_path, settings, kwargs):
    a = one(tmp_path, settings, MADRID, **kwargs)
    assert (a["physrisk_type"], a["type_source"]) == ("Buildings/Commercial", "assumed")
    assert a["assessable"] is True


def test_default_type_comes_from_settings(tmp_path, settings):
    from dataclasses import replace

    residential = replace(settings, default_building_type="Buildings/Residential")
    assert one(tmp_path, residential, MADRID)["physrisk_type"] == "Buildings/Residential"


@pytest.mark.parametrize(
    ("point", "region"),
    [
        (MADRID, "Europe"),
        (HOUSTON, "North America"),
        (NAIROBI, "Africa"),
        (SYDNEY, "Oceania"),
        ((-23.55, -46.63), "South America"),
        (MANILA, "Asia"),
        (BARISAL, "Asia"),
    ],
)
def test_regions(tmp_path, settings, point, region):
    a = one(tmp_path, settings, point, subtype="industrial")
    assert a["region"] == region
    assert a["assessable"] is True


def test_exact_location_is_used_when_a_curve_exists(tmp_path, settings):
    a = one(tmp_path, settings, MADRID, subtype="commercial")
    assert (a["physrisk_location"], a["location_fallback"]) == ("Europe", False)


@pytest.mark.parametrize(("point", "subtype"), [(NAIROBI, "commercial"), (SYDNEY, "industrial")])
def test_missing_pair_falls_back_to_global_and_says_so(tmp_path, settings, point, subtype):
    a = one(tmp_path, settings, point, subtype=subtype)
    assert (a["physrisk_location"], a["location_fallback"]) == ("Global", True)


def test_mid_ocean_with_no_building_is_excluded(tmp_path, settings):
    a = one(tmp_path, settings, MID_ATLANTIC, match_type="none")
    assert a["assessable"] is False
    assert a["exclusion_reason"] == "off_land"
    assert a["physrisk_type"] is None
    assert a["physrisk_location"] is None


def test_land_with_no_building_is_assumed(tmp_path, settings):
    a = one(tmp_path, settings, MADRID, match_type="none")
    assert a["assessable"] is True
    assert a["type_source"] == "assumed"


def test_near_a_coast_with_no_building_counts_as_land(tmp_path, settings):
    a = one(tmp_path, settings, OFF_LISBON, match_type="none")
    assert a["assessable"] is True
    assert a["region_source"] == "nearest"
    assert a["region"] == "Europe"
    assert 0 < a["region_distance_km"] < 50


def test_nearest_distance_is_in_kilometres(tmp_path, settings):
    # Worked by hand: 0.525 degrees of latitude and 1.024 of longitude, at about 47 km per degree of
    # longitude this far north. A swapped lat/lon would come out over 100 km.
    a = one(tmp_path, settings, WEST_OF_ICELAND, match_type="none")
    assert a["region_source"] == "nearest"
    assert a["region_distance_km"] == pytest.approx(EXPECTED_KM, abs=3)


def test_matched_building_proves_land_at_any_distance(tmp_path, settings):
    a = one(tmp_path, settings, REMOTE, subtype="commercial")
    assert a["assessable"] is True
    assert a["region_source"] == "nearest"
    assert a["region_distance_km"] > 50


def test_invalid_rows_are_excluded(tmp_path, settings):
    a = one(tmp_path, settings, None, match_type="invalid")
    assert a["assessable"] is False
    assert a["exclusion_reason"] == "invalid"
    assert a["region"] is None


def test_no_curve_at_all_is_excluded(tmp_path, settings):
    a = one(tmp_path, settings, ANTARCTICA, subtype="residential")
    assert a["exclusion_reason"] == "no_curve"
    assert a["assessable"] is False
    assert a["physrisk_type"] == "Buildings/Residential"
    assert a["physrisk_location"] is None


def test_summary_counts(tmp_path, settings):
    _, summary = classify_rows(
        tmp_path,
        settings,
        (MADRID, {"subtype": "residential"}),
        (HOUSTON, {}),
        (NAIROBI, {"subtype": "commercial"}),
        (MID_ATLANTIC, {"match_type": "none"}),
        (None, {"match_type": "invalid"}),
    )
    assert summary == {
        "assessable": 3,
        "assumed_type": 1,
        "global_curve": 1,
        "excluded_off_land": 1,
        "excluded_invalid": 1,
    }


def test_classification_keeps_keys_and_order(tmp_path, settings):
    rows, _ = classify_rows(tmp_path, settings, (MADRID, {}), (None, {"match_type": "invalid"}))
    assert [(r["row_num"], r["asset_id"]) for r in rows] == [(1, "a1"), (2, "a2")]


def map_rows():
    with open(TYPE_MAP, newline="") as f:
        return list(csv.DictReader(f))


def test_every_mapped_type_is_a_configured_type():
    assert {r["physrisk_type"] for r in map_rows() if r["physrisk_type"]} == set(BUILDING_TYPES)


def test_map_keys_are_unique():
    keys = [(r["source"], r["value"]) for r in map_rows()]
    assert len(keys) == len(set(keys))


def test_every_configured_type_has_a_curve():
    assert set(BUILDING_TYPES) <= {building_type for building_type, _ in valid_curves()}


def test_known_gaps_in_the_curves_are_handled():
    # If physrisk fills these, the fallback tests above need new examples.
    curves = valid_curves()
    assert ("Buildings/Commercial", "Africa") not in curves
    assert ("Buildings/Industrial", "Oceania") not in curves
    assert ("Buildings/Residential", "Global") not in curves
    assert ("Buildings/Commercial", "Global") in curves
    assert ("Buildings/Industrial", "Global") in curves


def test_unknown_type_fails_loudly():
    with pytest.raises(ClassificationError, match="Buildings/Nonsense"):
        check_building_types("Buildings/Nonsense")


def test_map_type_outside_the_curves_fails_loudly():
    with pytest.raises(ClassificationError, match="Buildings/Residential"):
        check_building_types(
            "Buildings/Commercial",
            {("Buildings/Commercial", "Global"), ("Buildings/Industrial", "Global")},
        )


def test_country_data_has_the_expected_shape():
    features = json.loads(COUNTRIES.read_text())["features"]
    assert len(features) == 242
    assert {f["properties"]["region"] for f in features} == {
        "Africa",
        "Antarctica",
        "Asia",
        "Europe",
        "North America",
        "Oceania",
        "South America",
    }
