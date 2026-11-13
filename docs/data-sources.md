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
