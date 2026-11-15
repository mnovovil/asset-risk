"""Tropical cyclone wind map tiles, drawn from the IRIS wind array on physrisk's public S3 bucket.

physrisk's image API won't draw this resource either, so grid_layer.py reads it anonymously and
draws the tiles. Facts that hold for physrisk-lib 1.10.6, checked by test/engine/test_wind_map.py,
and against the real bucket by test/engine/test_wind_map_live.py (-m s3):
- the path is wind/iris/v1/max_speed_{scenario}_{year}, the resource physrisk's wind damage reads:
  CoreInventorySourcePaths._select_wind prefers group iris_osc, and every wind impact in a run lists
  this path. Jupiter's wind/jupiter/v1/max_1min_... array only feeds physrisk's Jupiter exposure
  measure, so it isn't the one mapped. physrisk applies no scaling to IRIS before working out
  damage (only fire is divided by 500), so the map and the losses are on the same scale
- historical (2010), and ssp119, ssp245 and ssp585 for 2050 only. physrisk weights the baseline and
  2050 to estimate other years (interpolate_years), which the map doesn't: only an exact match in
  the inventory gets a map. There's no ssp126, and physrisk returns no wind for it either
- units m/s and a colour scale from 0 to 90 m/s, from the inventory. The array has no units attr
- a (19, 1200, 3600) float32 array of return periods 10 to 1000 years (index_values), on a 0.1
  degree EPSG:4326 grid from 60 N to 60 S, transform_mat3x3 about [0.1, 0, -180, 0, -0.1, 60]. Its
  chunks are (19, 250, 250), so reading one return period still downloads every chunk, about 73 MB
- NaN (about 65% of cells) is where IRIS has no tropical cyclone, which includes most land outside
  the tropics, and is drawn transparent. Beyond 60 degrees is outside the grid, and clear too

The 100-year return period is shown: physrisk works out damage from all 19, and the flood map's 1000
years is far into IRIS's synthetic record.
"""

from __future__ import annotations

from engine.grid_layer import Coverage, GridLayer, GridSettings, GridSpec

HAZARD = "Wind"
WIND_PATH = "wind/iris/v1/max_speed_{scenario}_{year}"
RETURN_PERIOD = 100
# A 0.1 degree cell is about 18 px wide at zoom 7 at the equator: deeper tiles would add nothing.
MAX_ZOOM = 7

# Lowest value to highest, one hue (OKLCH hue 162, as wind's --series-3 in styles.css), lightness
# falling 0.74 to 0.42, so it reads apart from wildfire's hue 45. One ramp serves both themes. The
# dataviz validator's --ordinal checks, against the --surface colours in app/front/src/styles.css:
#   node scripts/validate_palette.js "#5ac293,#2eaa79,#1a9064,#107550,#115b3e" \
#     --mode light --surface "#fcfcfb" --ordinal    -> ALL CHECKS PASS (2026-11-14)
#   node scripts/validate_palette.js "#5ac293,#2eaa79,#1a9064,#107550,#115b3e" \
#     --mode dark --surface "#0d0d0d" --ordinal     -> ALL CHECKS PASS (2026-11-14)
# Re-run both before changing it.
RAMP = ("#5ac293", "#2eaa79", "#1a9064", "#107550", "#115b3e")

MEASURE = "Tropical cyclone wind speed (1-minute sustained)"
NO_DATA_LABEL = "No tropical cyclone in the data, or beyond 60° north or south"
NOTE = (
    "The 1-minute sustained wind speed that tropical cyclones reach about once in 100 years, from "
    "IRIS's synthetic storms. physrisk works out wind damage from every return period, 10 to 1000 "
    "years, and its wind losses come from these storms only, so a clear area has no wind loss "
    "either. physrisk "
    "estimates years other than 2050 from this and the baseline, and the map shows only the years "
    "in the data. Cells are about 10 km across, so the map shows the region, not the property. A "
    "low or empty area is not proof of low risk."
)
OTHER_YEARS = ". physrisk estimates the other years' losses from it and the baseline"


def _source(cover: Coverage) -> str:
    credit = f" {cover.attribution.rstrip('.')}." if cover.attribution else ""
    return (
        "Source: IRIS, the Imperial College Storm Model, via OS-Climate physrisk."
        f'{credit} physrisk lists its licence as "{cover.licence}".'
    )


SPEC = GridSpec(
    hazard=HAZARD,
    noun="tropical cyclone wind",
    measure=MEASURE,
    ramp=RAMP,
    no_data_label=NO_DATA_LABEL,
    note=NOTE,
    source=_source,
    return_period=RETURN_PERIOD,
    other_years=OTHER_YEARS,
)


def configure(
    path: str = WIND_PATH, max_zoom: int = MAX_ZOOM, settings: GridSettings | None = None
) -> GridLayer:
    """The wind layer, built from the run settings."""
    return GridLayer(SPEC, path, max_zoom, settings)
