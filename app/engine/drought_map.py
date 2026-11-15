"""Drought map tiles, drawn from OS-Climate's 12-month SPEI array on physrisk's public S3 bucket.

physrisk's image API won't draw this resource, so grid_layer.py reads it anonymously and draws the
tiles. Facts that hold for physrisk-lib 1.10.6, checked by test/engine/test_drought_map.py, and
against the real bucket by test/engine/test_drought_map_live.py (-m s3):
- the inventory path is drought/osc/v2/months_spei12m_below_threshold_{gcm}_{scenario}_{year},
  indicator months/spei12m/below/threshold, with gcm multi_model_0 or one of six single models.
  CoreInventorySourcePaths._select_drought picks multi_model_0, so that's the one mapped. The
  Jupiter months_spei3m_below_-2 array isn't: only a placeholder model uses it, and it has no
  ssp245 or baseline
- physrisk models no drought loss for this app's buildings. Its one drought curve is
  ManufacturingAsset disruption (threshold/piecewise_linear: none at SPEI -2, rising to all of it
  at -3.5), and it doesn't rescale the values (_adjust_indicator_values). Runs have no drought
  impacts, and their drought scores are "No vulnerability", which the dashboard shows as "No model"
- historical (2005), and ssp126, ssp245 and ssp585 for 2030, 2040, 2050 and 2080: every default
  scenario and year, and the baseline. Units months/year and a colour scale from 0 to 12 months, all
  from the inventory, which lists no licence, source or attribution
- each path is a zarr group (store_netcdf_coords): indicator, latitude, longitude and threshold.
  indicator is a (7, 600, 1440) float64 array, chunks (7, 256, 256), on a 0.25 degree EPSG:4326
  grid from 90 N to 60 S, transform_mat3x3 [0.25, 0, -180, 0, -0.25, 90]. Its thresholds are in
  the attr threshold_values [0, -1, -1.5, -2, -2.5, -3, -3.6] (the inventory's map.index_values
  don't match them). Reading one threshold downloads every chunk, 10 to 13 MB, in about 0.5 s, and
  keeps 3.5 MB as float32
- open water is stored as 0, not NaN: about 97% of sea points are 0 at every threshold, even SPEI
  below 0, against 0.2% of land points. So 0 is drawn clear (zero_is_no_data), taking the rare land
  cell with no months below the threshold with it

SPEI -2 is shown: "extreme drought" on the SPEI scale, and where physrisk's manufacturing disruption
curve starts. The baseline is far milder than the projections (99th percentile 0.4 months against
8 for ssp585 2050), as SPEI is measured against the historical climate.

The source array is read, not maps/drought/osc/v2/..._map: that is physrisk's two-level EPSG:3857
display pyramid (map_array_pyramid), already resampled.
"""

from __future__ import annotations

from engine.grid_layer import Coverage, GridLayer, GridSettings, GridSpec

HAZARD = "Drought"
GCM = "multi_model_0"  # what physrisk's _select_drought picks
DROUGHT_PATH = f"drought/osc/v2/months_spei12m_below_threshold_{GCM}_{{scenario}}_{{year}}"
THRESHOLD = -2.0  # SPEI: "extreme drought", and where the manufacturing disruption curve starts
RETURN_PERIOD = None  # the index is a threshold, not a return period
# A 0.25 degree cell is about 23 px wide at zoom 6: deeper tiles would add nothing.
MAX_ZOOM = 6

# Lowest value to highest, one hue (OKLCH hue 25, as drought's --series-8 in styles.css), lightness
# falling 0.74 to 0.42. The hue is 20 degrees from wildfire's 45, because --series-8 is red; only
# one hazard map shows at a time, and the legend names it. One ramp serves both themes. The dataviz
# validator's --ordinal checks, against the --surface colours in app/front/src/styles.css:
#   node scripts/validate_palette.js "#fe7f77,#f15653,#d43a3b,#b71723,#940216" \
#     --mode light --surface "#fcfcfb" --ordinal    -> ALL CHECKS PASS (2026-11-15)
#   node scripts/validate_palette.js "#fe7f77,#f15653,#d43a3b,#b71723,#940216" \
#     --mode dark --surface "#0d0d0d" --ordinal     -> ALL CHECKS PASS (2026-11-15)
# Re-run both before changing it.
RAMP = ("#fe7f77", "#f15653", "#d43a3b", "#b71723", "#940216")

MEASURE = "Months a year with 12-month SPEI below −2 (extreme drought)"
NO_DATA_LABEL = "Open water (stored as 0), or no months below −2"
NOTE = (
    "Months a year when the 12-month Standardized Precipitation Evapotranspiration Index is below "
    "−2, a 20-year mean across several climate models (multi_model_0). physrisk models no drought "
    "loss for these buildings, only disruption to manufacturing, so the results show No model. The "
    "baseline is 2005, and projections run much higher because SPEI is measured against the past "
    "climate. Cells are about 25 km across, so the map shows the region, not the property. A low "
    "or empty area is not proof of low risk."
)
OTHER_YEARS = ". physrisk estimates the other years from the years either side"


def _source(cover: Coverage) -> str:
    credit = f" {cover.attribution.rstrip('.')}." if cover.attribution else ""
    if cover.licence == "not stated":
        licence = " physrisk lists no licence for them."
    else:
        licence = f' physrisk lists its licence as "{cover.licence}".'
    return f"Source: OS-Climate physrisk's drought indicators.{credit}{licence}"


SPEC = GridSpec(
    hazard=HAZARD,
    noun="drought",
    measure=MEASURE,
    ramp=RAMP,
    no_data_label=NO_DATA_LABEL,
    note=NOTE,
    source=_source,
    return_period=RETURN_PERIOD,
    other_years=OTHER_YEARS,
    params={"gcm": GCM},
    index_value=THRESHOLD,
    index_attr="threshold_values",
    zero_is_no_data=True,
)


def configure(
    path: str = DROUGHT_PATH, max_zoom: int = MAX_ZOOM, settings: GridSettings | None = None
) -> GridLayer:
    """The drought layer, built from the run settings."""
    return GridLayer(SPEC, path, max_zoom, settings)
