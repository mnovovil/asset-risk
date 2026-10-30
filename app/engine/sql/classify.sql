-- Turn each geolocated row into a physrisk type and location, recording how each was decided.
-- Needs the temp tables building_type_map, valid_curves and asset_regions.
-- Parameters: the km limit for trusting a nearest country, then the default building type.
UPDATE assets AS a
SET region = c.region,
    region_source = c.region_source,
    region_distance_km = c.region_distance_km,
    physrisk_type = c.physrisk_type,
    physrisk_location = c.physrisk_location,
    location_fallback = c.location_fallback,
    type_source = c.type_source,
    assessable = c.exclusion_reason IS NULL,
    exclusion_reason = c.exclusion_reason
FROM (
    WITH regioned AS (
        -- A matched building proves the point is on land, however far the coarse country data is.
        SELECT a.row_num,
               a.match_type,
               a.class,
               a.subtype,
               r.region_source,
               r.region_distance_km,
               CASE
                   WHEN a.match_type IN ('intersects', 'nearest') OR r.region_distance_km <= ?
                       THEN r.region
               END AS region
        FROM assets a
        LEFT JOIN asset_regions r USING (row_num)
    ),
    typed AS (
        SELECT g.*,
               coalesce(by_class.physrisk_type, by_subtype.physrisk_type, ?) AS building_type,
               CASE
                   WHEN by_class.physrisk_type IS NOT NULL THEN 'class'
                   WHEN by_subtype.physrisk_type IS NOT NULL THEN 'subtype'
                   ELSE 'assumed'
               END AS type_source
        FROM regioned g
        LEFT JOIN building_type_map by_class
            ON by_class.source = 'class' AND by_class.value = g.class
        LEFT JOIN building_type_map by_subtype
            ON by_subtype.source = 'subtype' AND by_subtype.value = g.subtype
    ),
    located AS (
        SELECT t.*,
               exact.location IS NOT NULL AS has_exact,
               global.location IS NOT NULL AS has_global
        FROM typed t
        LEFT JOIN valid_curves exact
            ON exact.building_type = t.building_type AND exact.location = t.region
        LEFT JOIN valid_curves global
            ON global.building_type = t.building_type AND global.location = 'Global'
    ),
    decided AS (
        SELECT *,
               CASE
                   WHEN match_type = 'invalid' THEN 'invalid'
                   WHEN region IS NULL THEN 'off_land'
                   WHEN NOT has_exact AND NOT has_global THEN 'no_curve'
               END AS exclusion_reason
        FROM located
    )
    SELECT row_num,
           region,
           region_source,
           region_distance_km,
           exclusion_reason,
           CASE WHEN exclusion_reason IN ('invalid', 'off_land') THEN NULL ELSE building_type END
               AS physrisk_type,
           CASE WHEN exclusion_reason IN ('invalid', 'off_land') THEN NULL ELSE type_source END
               AS type_source,
           CASE
               WHEN exclusion_reason IS NOT NULL THEN NULL
               WHEN has_exact THEN region
               ELSE 'Global'
           END AS physrisk_location,
           CASE WHEN exclusion_reason IS NOT NULL THEN NULL ELSE NOT has_exact END
               AS location_fallback
    FROM decided
) AS c
WHERE a.row_num = c.row_num
