-- Find each valid point's region. Points inside no country (coarse coastlines, small islands, open
-- sea) take the nearest one, with its distance so the caller can decide whether to believe it.
-- "Nearest" is measured in degrees, which is enough to pick a country, then that gap in km.
CREATE OR REPLACE TEMP TABLE asset_regions AS
WITH points AS (
    SELECT row_num, ST_Point(lon, lat) AS pt FROM assets WHERE match_type <> 'invalid'
),
inside AS (
    SELECT p.row_num, min(r.region) AS region
    FROM points p
    JOIN regions r ON ST_Intersects(r.geom, p.pt)
    GROUP BY p.row_num
),
outside AS (
    SELECT p.row_num,
           r.region,
           ST_ShortestLine(r.geom, p.pt) AS gap
    FROM points p
    CROSS JOIN regions r
    WHERE p.row_num NOT IN (SELECT row_num FROM inside)
    QUALIFY row_number() OVER (PARTITION BY p.row_num ORDER BY ST_Distance(r.geom, p.pt)) = 1
)
SELECT row_num, region, 'contains' AS region_source, 0.0 AS region_distance_km FROM inside
UNION ALL
SELECT row_num,
       region,
       'nearest',
       ST_Distance_Sphere(ST_StartPoint(gap), ST_EndPoint(gap)) / 1000
FROM outside
