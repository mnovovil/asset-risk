-- What the API and dashboard read. Portfolio figures are equal-weighted means, because a portfolio
-- of id, lat, lon has no asset values to weight by.

-- Hazards with results in every scenario and year. Data differs by scenario (ssp245 has no fire or
-- hail, for example), so only totals over these can be compared across scenarios.
CREATE VIEW v_shared_hazards AS
SELECT hazard
FROM impacts
GROUP BY hazard
HAVING count(DISTINCT (scenario, year)) = (
    SELECT count(DISTINCT (scenario, year)) FROM impacts
);

CREATE VIEW v_asset_hazard_aal AS
SELECT a.row_num, a.asset_id, a.lat, a.lon, i.scenario, i.year, i.hazard, i.impact_type, i.aal,
       i.aal_std, i.hazard_paths
FROM impacts i
JOIN assets a USING (row_num);

CREATE VIEW v_asset_totals AS
SELECT a.row_num,
       a.asset_id,
       i.scenario,
       i.year,
       sum(i.aal) AS total_aal,
       sum(i.aal) FILTER (WHERE i.hazard IN (SELECT hazard FROM v_shared_hazards)) AS shared_aal,
       count(DISTINCT i.hazard) AS hazards
FROM impacts i
JOIN assets a USING (row_num)
GROUP BY a.row_num, a.asset_id, i.scenario, i.year;

CREATE VIEW v_asset_scores AS
SELECT a.row_num, a.asset_id, s.scenario, s.year, s.hazard, s.score, s.label
FROM scores s
JOIN assets a USING (row_num);

CREATE VIEW v_portfolio_hazards AS
SELECT scenario, year, hazard, avg(aal) AS mean_aal, count(DISTINCT row_num) AS assets
FROM impacts
GROUP BY scenario, year, hazard;

-- One row per requested scenario and year, including any that returned nothing.
CREATE VIEW v_portfolio_trajectory AS
SELECT p.scenario,
       p.year,
       coalesce(count(t.row_num), 0) AS assets,
       avg(t.total_aal) AS mean_total_aal,
       avg(t.shared_aal) AS mean_shared_aal,
       coalesce(max(t.hazards), 0) AS hazards
FROM assessment_pairs p
LEFT JOIN v_asset_totals t ON t.scenario = p.scenario AND t.year IS NOT DISTINCT FROM p.year
GROUP BY p.scenario, p.year;

-- Every hazard seen in the run against every requested scenario and year, to show what's missing.
CREATE VIEW v_hazard_coverage AS
SELECT p.scenario,
       p.year,
       h.hazard,
       count(DISTINCT i.row_num) AS assets,
       count(DISTINCT i.row_num) > 0 AS covered,
       h.hazard IN (SELECT hazard FROM v_shared_hazards) AS shared
FROM assessment_pairs p
CROSS JOIN (SELECT DISTINCT hazard FROM impacts) h
LEFT JOIN impacts i
    ON i.scenario = p.scenario AND i.year IS NOT DISTINCT FROM p.year AND i.hazard = h.hazard
GROUP BY p.scenario, p.year, h.hazard;

CREATE VIEW v_exclusions AS
SELECT exclusion_reason AS reason, count(*) AS assets
FROM assets
WHERE exclusion_reason IS NOT NULL
GROUP BY exclusion_reason;

CREATE VIEW v_portfolio_summary AS
SELECT count(*) AS total_assets,
       count(*) FILTER (WHERE assessable) AS assessable,
       count(*) FILTER (WHERE NOT assessable) AS excluded,
       count(*) FILTER (WHERE assessable AND type_source = 'assumed') AS assumed_type,
       count(*) FILTER (WHERE assessable AND location_fallback) AS global_curve,
       count(*) FILTER (WHERE assessable AND match_type = 'nearest') AS nearest_match,
       count(*) FILTER (WHERE assessable AND match_type = 'none') AS no_building,
       (SELECT count(DISTINCT row_num) FROM assess_failures) AS failed_assets
FROM assets;
