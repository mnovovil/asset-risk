-- Copy FEMA's flood hazard polygons (NFHL S_FLD_HAZ_AR) out of the temp view flood_zone_source_rows,
-- whose geometry column is named geom. Polygons come out in OGC:CRS84 (lon, lat), sorted along a
-- Hilbert curve so neighbours sit together on disk; flood_zone_data.py then adds the R-tree.
-- Parameters: $reproject, then $source_crs, which is only read when $reproject is true.
CREATE TABLE flood_zones AS
WITH kept AS (
    SELECT DFIRM_ID, VERSION_ID, FLD_AR_ID, FLD_ZONE, ZONE_SUBTY, SFHA_TF, STATIC_BFE, V_DATUM, DEPTH,
           LEN_UNIT, VELOCITY, VEL_UNIT,
           CASE
               WHEN $reproject THEN ST_Transform(geom, $source_crs, 'OGC:CRS84', always_xy := true)
               ELSE geom
           END AS lonlat
    FROM flood_zone_source_rows
    WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) AND FLD_ZONE IS NOT NULL
)
SELECT * EXCLUDE (lonlat), ST_SetCRS(lonlat, 'OGC:CRS84') AS geom
FROM kept
ORDER BY ST_Hilbert(lonlat, {'min_x': -180, 'min_y': -90, 'max_x': 180, 'max_y': 90}::BOX_2D),
         FLD_AR_ID
