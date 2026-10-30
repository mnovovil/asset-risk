-- One file per run. Later stages add their columns and tables here.
CREATE TABLE runs (
    run_id      VARCHAR PRIMARY KEY,
    source_name VARCHAR,  -- the uploaded file's name: a label only, never used as a path
    total_rows  INTEGER NOT NULL,
    status      VARCHAR NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'interrupted')),
    stage       VARCHAR,  -- geolocating | classifying | assessing
    done        INTEGER NOT NULL DEFAULT 0,  -- progress within the stage
    total       INTEGER NOT NULL DEFAULT 0,
    error       VARCHAR,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
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
    geometry_wkt VARCHAR,

    -- Filled in by classify.sql.
    region             VARCHAR,  -- continent from the country data; NULL when there is none nearby
    region_source      VARCHAR,  -- contains | nearest
    region_distance_km DOUBLE,   -- how far away the nearest country is; 0 when inside one
    physrisk_type      VARCHAR,
    physrisk_location  VARCHAR,
    location_fallback  BOOLEAN,  -- physrisk_location is Global because region has no curve
    type_source        VARCHAR,  -- class | subtype | assumed
    assessable         BOOLEAN,
    exclusion_reason   VARCHAR   -- invalid | off_land | no_curve
);

-- Each scenario and year physrisk was asked for, so one that returns nothing still shows up. The
-- historical baseline has year NULL.
CREATE TABLE assessment_pairs (
    scenario VARCHAR NOT NULL,
    year     INTEGER
);

-- One row per asset, hazard, impact type, scenario and year. The baseline comes back with every
-- request and is stored once.
CREATE TABLE impacts (
    row_num      INTEGER NOT NULL,
    hazard       VARCHAR NOT NULL,
    impact_type  VARCHAR NOT NULL,
    scenario     VARCHAR NOT NULL,
    year         INTEGER,
    aal          DOUBLE,  -- average annual loss, as a fraction of asset value
    aal_std      DOUBLE,
    hazard_paths VARCHAR[]  -- the data sets behind the number
);

-- Separate from impacts because physrisk scores hazards it has no impact result for, which is how
-- "No vulnerability" and "No hazard data" are told apart from a low score.
CREATE TABLE scores (
    row_num  INTEGER NOT NULL,
    hazard   VARCHAR NOT NULL,
    scenario VARCHAR NOT NULL,
    year     INTEGER,
    score    INTEGER NOT NULL,
    label    VARCHAR
);

-- A batch that failed for one scenario and year. Its assets have no results for that pair, which
-- must not read as zero loss.
CREATE TABLE assess_failures (
    row_num  INTEGER NOT NULL,
    scenario VARCHAR NOT NULL,
    year     INTEGER NOT NULL,
    error    VARCHAR
);
