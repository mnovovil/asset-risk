-- One file per run. Later stages add their columns and tables here.
CREATE TABLE runs (
    run_id      VARCHAR PRIMARY KEY,
    source_name VARCHAR,  -- the uploaded file's name: a label only, never used as a path
    total_rows  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

-- One row per input row, in input order. Rows geolocate calls invalid are kept, so asset_id, lat
-- and lon can be NULL, and row_num is the key.
CREATE TABLE assets (
    row_num      INTEGER PRIMARY KEY,
    asset_id     VARCHAR,
    lat          DOUBLE,
    lon          DOUBLE,
    match_type   VARCHAR NOT NULL
        CHECK (match_type IN ('intersects', 'nearest', 'none', 'invalid')),
    distance_m   DOUBLE,
    building_id  VARCHAR,
    name         VARCHAR,
    class        VARCHAR,
    subtype      VARCHAR,
    height       DOUBLE,
    num_floors   INTEGER,
    geometry_wkt VARCHAR
);
