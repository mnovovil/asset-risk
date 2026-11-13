-- Match one tile of points to the FEMA polygons in the attached database fema. The envelope filter
-- is a constant, which is what lets DuckDB use the R-tree: only polygons near the tile are read.
-- ST_Intersects, not ST_Contains: a point on the line between two polygons matches both, and
-- flood_zones.sql picks one, where ST_Contains would match neither and call it not mapped.
-- Parameters: $west, $south, $east, $north (the tile's points' extent), $tile_x, $tile_y.
INSERT INTO flood_zone_matches
SELECT p.row_num, z.DFIRM_ID, z.FLD_AR_ID, z.FLD_ZONE, z.ZONE_SUBTY, z.SFHA_TF, z.STATIC_BFE,
       z.V_DATUM, z.LEN_UNIT, z.DEPTH
FROM (
    SELECT *
    FROM fema.flood_zones
    WHERE ST_Intersects(geom, ST_MakeEnvelope($west, $south, $east, $north))
) z
JOIN flood_zone_points p
    ON p.tile_x = $tile_x AND p.tile_y = $tile_y AND ST_Intersects(z.geom, p.pt)
