"""Large hail map tiles, drawn from Jupiter Intelligence's hail array on physrisk's public bucket.

physrisk's image API won't draw this resource (its group_id is jupiter_osc, not public), so
grid_layer.py reads it anonymously and draws the tiles. Facts that hold for physrisk-lib 1.10.6,
checked by test/engine/test_hail_map.py, and against the real bucket by
test/engine/test_hail_map_live.py (-m s3):
- the path is hail/jupiter/v1/days_above_5cm_{scenario}_{year}, the only Hail days/above/5cm
  resource. CoreInventorySourcePaths has no hail selector, so physrisk takes the first, and every
  hail impact in a run lists this path. _adjust_indicator_values rescales only fire, so the map is
  on the scale physrisk reads. Its damage curve (config_builders.py, occurrence_probability) then
  counts 1 in 50 of these potential large-hail days as a damaging hail day, at 0.1% damage for a
  generic asset: the map shows potential days, not damaging ones
- ssp126 and ssp585 for 2020, 2030, 2040, 2050, 2075 and 2100, and no historical scenario, units
  days/year, a colour scale from 0 to 4 days/year, licence "Commercial" and no attribution, all from
  the inventory. physrisk still gives baseline hail losses: with no historical scenario,
  scenario_paths_for_resource takes the earliest year of the first scenario, ssp126 2020. That
  isn't drawn as a baseline. It also estimates years not in the data (2080 is 0.8 x 2075 +
  0.2 x 2100). Only an exact inventory match gets a map, and there's no ssp245 for either
- a (1, 721, 1441) float32 array, chunks (1, 1000, 1000), on a 0.25 degree EPSG:4326 grid,
  transform_mat3x3 [0.25, 0, -180.125, 0, -0.25, 90.125], as fire's, with no index_values: one
  layer, so no return period. One array is about 0.9 MB on S3 and 4 MB in memory
- NaN (about 56% of cells) is no data: Antarctica and much of the open ocean, more so towards the
  south. Land points have values, and so do enclosed and coastal seas (the Gulf of Mexico, the
  Mediterranean, the Bay of Bengal). physrisk counts hail NaN as 0 (nan_is_zero), so a clear area
  has no hail loss either. 0 is a real value (about 31% of land) and gets the ramp's first colour

The source array is read, not its ..._map sibling: that is one array physrisk has already resampled
to EPSG:3857 (map.source "map_array", 1130 x 1125, about 35 km pixels), not a pyramid.
"""

from __future__ import annotations

from engine.grid_layer import Coverage, GridLayer, GridSettings, GridSpec

HAZARD = "Hail"
HAIL_PATH = "hail/jupiter/v1/days_above_5cm_{scenario}_{year}"
RETURN_PERIOD = None  # a single layer, not a stack of return periods
# A 0.25 degree cell is about 23 px wide at zoom 6: deeper tiles would add nothing.
MAX_ZOOM = 6

# Lowest value to highest, one hue (OKLCH hue 357, as hail's --series-5 in styles.css), lightness
# falling 0.74 to 0.42, so it reads apart from wildfire's hue 45 and wind's 162. One ramp serves
# both themes. The dataviz validator's --ordinal checks, against the --surface colours in
# app/front/src/styles.css:
#   node scripts/validate_palette.js "#f47fab,#d86693,#bd4e7b,#a23564,#87194e" \
#     --mode light --surface "#fcfcfb" --ordinal    -> ALL CHECKS PASS (2026-11-15)
#   node scripts/validate_palette.js "#f47fab,#d86693,#bd4e7b,#a23564,#87194e" \
#     --mode dark --surface "#0d0d0d" --ordinal     -> ALL CHECKS PASS (2026-11-15)
# Re-run both before changing it.
RAMP = ("#f47fab", "#d86693", "#bd4e7b", "#a23564", "#87194e")

MEASURE = "Days a year when hail over 5 cm is possible"
NO_DATA_LABEL = "No data (most open ocean, and Antarctica)"
NOTE = (
    "Days a year when the weather allows hail over 5 cm across, the mean of several downscaled "
    "climate models. physrisk counts about 1 in 50 of these as a damaging hail day, and has no "
    "hail loss where the map is clear. Its baseline hail losses use its ssp126 2020 data, which "
    "isn't shown as a baseline, and the map shows only the years in the data. Cells are about "
    "25 km across, so the map shows the region, not the property. A low or empty area is not "
    "proof of low risk."
)
OTHER_YEARS = ". physrisk estimates the other years' losses from the years either side"


def _source(cover: Coverage) -> str:
    credit = f" {cover.attribution.rstrip('.')}." if cover.attribution else ""
    return (
        "Source: Jupiter Intelligence, via OS-Climate physrisk."
        f'{credit} physrisk lists its licence as "{cover.licence}".'
    )


SPEC = GridSpec(
    hazard=HAZARD,
    noun="hail",
    measure=MEASURE,
    ramp=RAMP,
    no_data_label=NO_DATA_LABEL,
    note=NOTE,
    source=_source,
    return_period=RETURN_PERIOD,
    other_years=OTHER_YEARS,
)


def configure(
    path: str = HAIL_PATH, max_zoom: int = MAX_ZOOM, settings: GridSettings | None = None
) -> GridLayer:
    """The hail layer, built from the run settings."""
    return GridLayer(SPEC, path, max_zoom, settings)
