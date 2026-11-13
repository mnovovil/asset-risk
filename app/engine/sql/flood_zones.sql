-- One FEMA flood zone per asset from the matches. Needs the temp tables flood_zone_points,
-- flood_zone_matches and flood_zone_ranks (zone_key, risk_rank from fema_zones.json).
-- Parameter: $available, false when there was no flood zone database to look in.
--
-- Several polygons can cover a point: neighbours meet on a line, and FEMA's data has maps from
-- different studies over the same ground. The highest-risk zone wins, then a polygon that says it's
-- in the SFHA, then the higher base flood elevation, then DFIRM_ID and FLD_AR_ID so the choice is
-- always the same. fema_matches and fema_conflict keep the overlap visible.
INSERT INTO asset_flood_zones
WITH cleaned AS (
    SELECT row_num,
           DFIRM_ID AS dfirm_id,
           FLD_AR_ID AS fld_ar_id,
           FLD_ZONE AS fld_zone,
           CASE WHEN upper(trim(ZONE_SUBTY)) NOT IN ('', '<NULL>') THEN upper(trim(ZONE_SUBTY)) END
               AS zone_subtype,
           CASE SFHA_TF WHEN 'T' THEN true WHEN 'F' THEN false END AS in_sfha,  -- U stays NULL
           -- FEMA writes -9999 for null, and -8888 occurs too. No real elevation is that low.
           CASE WHEN STATIC_BFE > -8888 THEN STATIC_BFE END AS bfe,
           CASE WHEN DEPTH > -8888 THEN DEPTH END AS depth,
           CASE WHEN upper(trim(V_DATUM)) NOT IN ('', '<NULL>', '-9999', 'NP') THEN trim(V_DATUM) END
               AS datum,
           CASE WHEN upper(trim(LEN_UNIT)) NOT IN ('', '<NULL>', '-9999') THEN lower(trim(LEN_UNIT))
           END AS unit
    FROM flood_zone_matches
),
keyed AS (
    SELECT *,
           CASE
               WHEN fld_zone <> 'X' THEN fld_zone
               WHEN zone_subtype = 'AREA OF MINIMAL FLOOD HAZARD' THEN 'X_UNSHADED'
               WHEN zone_subtype IS NOT NULL THEN 'X_SHADED'  -- every other X subtype is shaded
               ELSE 'X'                                       -- shading not recorded
           END AS zone_key
    FROM cleaned
),
ranked AS (
    SELECT k.*,
           count(*) OVER (PARTITION BY k.row_num) AS matches,
           row_number() OVER (
               PARTITION BY k.row_num
               ORDER BY coalesce(r.risk_rank, 99), k.in_sfha DESC NULLS LAST,
                        k.bfe DESC NULLS LAST, k.dfirm_id, k.fld_ar_id
           ) AS pick
    FROM keyed k
    LEFT JOIN flood_zone_ranks r USING (zone_key)
),
conflicts AS (
    SELECT row_num, count(DISTINCT zone_key) > 1 AS conflict FROM keyed GROUP BY row_num
)
SELECT a.row_num,
       CASE
           WHEN a.match_type = 'invalid' THEN 'not_located'
           WHEN p.row_num IS NULL THEN 'not_us'
           WHEN NOT $available THEN 'unavailable'
           WHEN r.row_num IS NULL THEN 'not_mapped'
           ELSE 'mapped'
       END,
       r.fld_zone,
       r.zone_subtype,
       r.zone_key,
       r.in_sfha,
       r.bfe,
       CASE WHEN r.bfe IS NOT NULL THEN r.unit END,
       CASE WHEN r.bfe IS NOT NULL THEN r.datum END,
       r.depth,
       CASE WHEN r.depth IS NOT NULL THEN r.unit END,
       r.dfirm_id,
       r.fld_ar_id,
       coalesce(r.matches, 0),
       coalesce(c.conflict, false)
FROM assets a
LEFT JOIN flood_zone_points p USING (row_num)
LEFT JOIN ranked r ON r.row_num = a.row_num AND r.pick = 1
LEFT JOIN conflicts c ON c.row_num = a.row_num
