-- Load geolocate's output CSV. Its columns are a public interface; see its docs/reference.md.
-- Everything is read as text, as written, and cast here so a bad value becomes NULL and not an
-- error. A footprint can be a very long line of WKT, hence the large max_line_size.
INSERT INTO assets (
    row_num, asset_id, lat, lon, match_type, distance_m, building_id, name, class, subtype, height,
    num_floors, geometry_wkt
)
SELECT row_number() OVER () AS row_num,
       id,
       TRY_CAST(lat AS DOUBLE),
       TRY_CAST(lon AS DOUBLE),
       match_type,
       TRY_CAST(distance_m AS DOUBLE),
       building_id,
       name,
       class,
       subtype,
       TRY_CAST(height AS DOUBLE),
       TRY_CAST(num_floors AS INTEGER),
       geometry_wkt
FROM read_csv(
    ?,
    header = true,
    all_varchar = true,
    delim = ',',
    quote = '"',
    escape = '"',
    parallel = false,
    max_line_size = 100000000
)
