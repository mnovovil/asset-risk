-- The points to look up: valid rows whose country is the US or one of its territories, by the same
-- trust rule classify.sql uses for regions. Each is put in a square tile, and lookups go one tile
-- at a time. Parameters: $tile_deg (the tile's side in degrees), $us_countries.
CREATE OR REPLACE TEMP TABLE flood_zone_points AS
SELECT row_num,
       ST_Point(lon, lat) AS pt,
       floor(lon / $tile_deg)::INTEGER AS tile_x,
       floor(lat / $tile_deg)::INTEGER AS tile_y
FROM assets
WHERE match_type <> 'invalid'
  AND lat BETWEEN -90 AND 90
  AND lon BETWEEN -180 AND 180
  AND list_contains($us_countries, country)
