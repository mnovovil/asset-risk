# Data sources

## Regions

`app/engine/data/countries.geojson` gives each point the continent that picks physrisk's regional
vulnerability curve. It comes from [Natural Earth](https://www.naturalearthdata.com/) 1:50m Admin 0
countries, which is public domain, at the commit pinned in `script/build_regions.py`. Only each
country's name, region and shape are kept.

- Natural Earth files some small islands under "open ocean". Those use their UN region instead, and
  the Americas become South America.
- The coastline is coarse. A point inside no country takes the nearest one, up to 50 km away, unless
  it matched a building, which proves it is on land at any distance.
- Distances don't wrap around ±180° longitude, so a point just across the antimeridian from the
  nearest country can be treated as off land.

## Buildings

Building class and subtype come from [Overture Maps](https://overturemaps.org) through geolocate.
`app/engine/sql/building_type_map.csv` maps them to physrisk's three building types. `class` takes
precedence over `subtype`. Values with a blank type, such as `roof`, say nothing about a building's
use, so they fall through.

Run `script/overture_values.py` to audit the map against a release. In a sample of 6 files from
release 2026-10-21.0 (about 29.8 million buildings), 97% had no `subtype` and no `class`. Those
assets use `default_building_type`, and the type is recorded as `assumed`. In this sample the map
covered every value.

The mapping involves judgement: farm buildings use the Industrial curve, domestic outbuildings use
Residential, and public buildings use Commercial.

## Hazard maps

The river and coastal flood maps are WRI Aqueduct Floods, drawn by physrisk. physrisk lists their
licence as the WRI Open Data Commitment.

The wildfire map is Jupiter Intelligence's fire probability, the resource
`fire/jupiter/v1/fire_probability_{scenario}_{year}` in physrisk's embedded inventory. physrisk's
wildfire damage figures use the same data. physrisk keeps it out of its public group (`group_id`
`jupiter_osc`) and won't draw it, but the arrays are in the public `os-climate-physical-risk`
bucket, so the app reads them anonymously:

```
s3://os-climate-physical-risk/hazard-indicators/hazard.zarr/fire/jupiter/v1/fire_probability_{scenario}_{year}
```

- zarr v2, float32, shape (1, 721, 1441), a 0.25° EPSG:4326 grid whose cell centres run from -180°
  to 180° inclusive. Its first and last columns are both at the antimeridian but hold different
  values, so the app reads each from its own side.
- About 71% of cells are NaN: ocean, or no data. 0 is a real value.
- SSP1-2.6 and SSP5-8.5 for 2020, 2030, 2040, 2050, 2075 and 2100, read from the inventory, with no
  historical baseline. The `..._map` array next to it is already in Web Mercator, but it's coarser
  (about 35 km) and resampled once, so the app uses the source array.
- **Licence: physrisk lists it as "Commercial".** The panel shows the source and that licence under
  the map.

The tropical cyclone wind map is IRIS, the Imperial College Storm Model: the resource
`wind/iris/v1/max_speed_{scenario}_{year}` (`group_id` `iris_osc`) in physrisk's embedded inventory.
It's the data physrisk's wind damage reads: its source paths prefer `iris_osc` for wind, and every
wind result's `hazard_paths` names it. Jupiter's `wind/jupiter/v1/max_1min_{scenario}_{year}` is
in the same bucket, but only physrisk's Jupiter exposure measure uses it, so it isn't mapped. The app
reads IRIS anonymously too:

```
s3://os-climate-physical-risk/hazard-indicators/hazard.zarr/wind/iris/v1/max_speed_{scenario}_{year}
```

- **Measure:** the 1-minute sustained wind speed of tropical cyclones, in m/s (from the inventory: the
  array has no units attribute), for return periods of 10 to 1000 years. The map shows the
  1-in-100-year speed. physrisk works out damage from all 19 return periods, and applies no scaling
  first, so the map and the losses are on the same scale.
- zarr v2, float32, shape (19, 1200, 3600): return period, then a **0.1° (about 10 km) EPSG:4326
  grid from 60° N to 60° S**, with no repeated column at the antimeridian. Chunks are (19, 250, 250),
  so reading one return period still downloads all of an array, about 73 MB (3.4 to 7 s when
  measured).
- About 65% of cells are NaN: where IRIS has no tropical cyclone, which includes most land outside
  the tropics (London and Denver, for example), as well as open ocean. Beyond 60° is outside the
  grid. Both are clear on the map.
- **Historical (2010), and SSP1-1.9, SSP2-4.5 and SSP5-8.5 for 2050 only**, read from the inventory.
  physrisk estimates other years by weighting the baseline and 2050, which a map can't show, so of
  this app's years only 2050 has a wind map. There's no SSP1-2.6 data, and physrisk returns no wind
  for it.
- **Licence: Creative Commons Attribution 4.0 (CC BY 4.0).** Attribution, which the panel shows under
  the map: Sparks, N. & Toumi, R. (2023). IRIS: The Imperial College Storm Model Dataset (v1).
  Figshare. https://doi.org/10.6084/m9.figshare.c.6724251.v1
- **A low or clear cell is not proof of low risk.** IRIS models tropical cyclones only, so other
  windstorms are in neither the map nor the losses.

## FEMA flood zones

FEMA's National Flood Hazard Layer flood hazard areas (`S_FLD_HAZ_AR`), as GeoParquet. The file
isn't in the repo: it's 2.5 GB and lives wherever you keep it, `data/` for example.

The GeoParquet has no bbox column or geometry statistics, so DuckDB can't skip any of it. Build it
once into a DuckDB file with an R-tree on the polygons, which lookups use:

```bash
.venv/bin/python script/build_flood_zones.py data/flood-hazard.parquet --as-of 2026-11-13
```

- `--as-of` is the date FEMA published the data or you downloaded it. It's stored with the database.
- The output goes to `data/fema/flood-zones.duckdb` by default, which is the `flood_zones_db`
  setting's default. Use `--out` to put it elsewhere, and point the setting at it.
- The national file took 67 s and peaked at about 5 GB of memory. The result is about 4.2 GB.
- Polygons come out in `OGC:CRS84` (lon, lat). A source in another CRS, such as NFHL's native NAD83
  (`EPSG:4269`), is reprojected. A source that doesn't say which CRS it uses is refused.
- Rows with no geometry or no `FLD_ZONE` are skipped and counted. A zone that
  `app/engine/data/fema_zones.json` doesn't list stops the build, so add it there first.

Docker mounts only this file, read-only, never the folder it's in.

### Checking against FEMA's map

`test/engine/fixtures/flood_zone_locations.json` lists 14 locations with a known zone: six street
addresses (Miami Beach, New Orleans, Charleston, Denver, Hoboken and Galveston) and a point in each
rarer zone. `test/engine/test_flood_zone_addresses.py` checks the lookup against them with FEMA's real
polygons, cut to a few hundred metres around each by `script/flood_zone_fixture.py`, with no network.

`pytest -m fema` asks FEMA's live map service for the same locations. On 2026-11-13, 12 of 14 agreed.
The two that differ are expected, and say why in the locations file:

- **Galveston Island Historic Pleasure Pier:** the data also has an older study's VE polygon here,
  and the highest-risk zone wins. FEMA's live map shows only open water.
- **Area not included, Lake County MT:** FEMA's live map returned no area at all.

After building the database from a new FEMA release:

1. Run `.venv/bin/python script/flood_zone_fixture.py`, then `.venv/bin/pytest
   test/engine/test_flood_zone_addresses.py`. A failure means the zone at a known location changed:
   check it, then update the locations file.
2. Run `.venv/bin/pytest -m fema`.
3. Check two or three addresses by hand on [FEMA's Flood Map Service Center](https://msc.fema.gov/portal/search):
   search the address, open the dynamic map, and compare the zone with the asset panel. Note the
   date you checked.
