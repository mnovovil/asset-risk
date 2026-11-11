# Methodology

How a coordinate becomes a risk figure, and how far to trust it. Start with the
[README](../README.md) for setup.

## From a point to a result

1. **Building.** geolocate finds the Overture building the point is inside, or the nearest one within
   100 m.
2. **Type.** The building's Overture `class` or `subtype` picks one of physrisk's building types:
   Residential, Commercial or Industrial.
3. **Region.** The point's continent picks the regional version of the damage curve.
4. **Assessment.** physrisk looks up each hazard at the point, turns its intensity into damage with a
   vulnerability curve, and returns the results.

## What the figures mean

**Average annual loss (AAL)** is the expected damage per year, as a share of asset value. A value of
0.5% means physrisk expects damage worth 0.5% of the asset per year on average. It isn't a forecast
for any one year.

An asset's **total** adds its hazards together.

The **portfolio mean** is equal-weighted, because a list of `id, lat, lon` has no asset values. A
small shed counts as much as a large factory. There are no currency figures for the same reason.

**Scores** are physrisk's bands of AAL, from "Very low impact" to "Very high impact". Thresholds
differ by hazard group.

**The historical baseline** comes from physrisk's own historical data.

## Comparing scenarios

physrisk's data doesn't cover the same hazards in every scenario, and it doesn't warn about this. For
one asset in Cologne, in 2030 and 2040:

| Scenario | Hazards returned |
|---|---|
| SSP5-8.5 | River flood, coastal flood, wind, wildfire, hail |
| SSP2-4.5 | River flood, coastal flood, wind |
| SSP1-2.6 | Wildfire, hail |
| SSP3-7.0 | None |

Totals from different scenarios therefore can't be compared directly. So:

- **Change over time** uses only the hazards every scenario has, and names them.
- **Historical markers** use only the hazards in the selected scenario.
- A scenario with no results is shown as having none, not as zero.

## Risk concentration

When the map opens, it shows only bubbles, one per group of nearby assets. Zooming in one level, or
clicking a bubble, replaces them with every individual asset, including those outside any group.
The legend says how many assets that is, and the score table and loss bars list every asset at any
zoom. An asset selected from them shows on the map whatever the zoom.

The groups come from [DBSCAN](https://en.wikipedia.org/wiki/DBSCAN), which needs no number of
clusters. An asset with at least `cluster_min_samples` assets within `cluster_eps_km` of it, itself
included, starts a cluster, and the cluster takes in every asset within that distance of its core.
Distances are along the Earth's surface. A portfolio with no dense group has no bubbles, and its
map shows every asset from the start. Clusters depend only on location, so
they're the same in every scenario and year.

A bubble's size grows with its number of assets. Its colour is the equal-weighted mean over its
members **with a result** for what the map is coloured by: total loss on the same scale as the
points, or a hazard's score rounded to the nearest band. Members with no model, no data or no
result are counted apart, and a bubble with no result is drawn hollow. Its tooltip says how many
members have results and how many assume the default building type.

Points and bubbles share one scale, from green (lowest) to red (highest). Each step is also darker
than the last (lighter, in dark mode), so the order reads without telling green from red.

For total loss, the five colours are **quintiles**: each holds about a fifth of the assets with a
result, for the selected scenario and year. One extreme loss then only moves the top class, instead
of pushing every other asset into the lowest one. The legend gives the range of losses in each
colour. The colour shows an asset's rank within this portfolio, so the same loss can be a different
colour in another portfolio or scenario. Hazard scores keep physrisk's fixed bands.

A green bubble or point is not proof of low risk, for the same reasons as a low score: see
[Limits of the model](#limits-of-the-model).

## Building type

**Most assets will have an assumed type.** In a sample of 6 parquet files from Overture release
2026-10-21.0 (about 29.8 million buildings), 97% had no `class` or `subtype`. Dense, well-mapped areas
do better: about half of a central Madrid sample had one.

An asset with no usable value uses `default_building_type`, and the dashboard shows the assumed share.
The choice affects flood results. At one Houston point, river flood AAL was about twice as high as
Residential than as Commercial. If your portfolio is mostly one type, set that as the default.

The mapping from Overture to physrisk also involves judgement, such as treating farm buildings as
Industrial. It's in `app/engine/sql/building_type_map.csv`.

A `nearest` match may be a neighbouring building, and the dashboard shows how far away it is.

**Height and floors don't affect results.** The default real estate curves depend only on type and
region. These fields are shown for context.

## Excluded assets

Excluded assets are counted and listed, and they never count as low risk.

| Reason | Meaning |
|---|---|
| `invalid` | Missing id, or a missing, non-numeric or out-of-range latitude or longitude |
| `off_land` | No building within range and no country within 50 km. Sent to physrisk, an ocean point would score "Very low" for flood, so a bad coordinate would look like a safe asset |
| `no_curve` | physrisk has no curve for this type and region, and no global one. Today this means a Residential building in Antarctica |

If physrisk has no curve for a type and region but has a global one, the asset uses the global curve,
and the dashboard says so. Commercial in Africa and Industrial in Oceania are the current cases.

If a physrisk request fails, its assets have no results for that scenario and year, and they're left
out of its means. That's reported as a failure and never counted as zero loss.

## Limits of the model

These come from physrisk's default data, and most were found while building
[the demo notebook](physrisk_demo.ipynb).

- **Resolution:** hazard data has pixels of about 1 km, so results depend on exact coordinates. Two
  points 1 km apart can differ a lot.
- **Flood protection:** flood results assume a global estimate of protection (FLOPROS), and no damage
  from floods below that standard. A site's real defences may be very different.
- **Climate model:** river flood comes from a single climate model, with no range of uncertainty, so
  changes between years may be noise.
- **Wind:** this means tropical cyclones. Zero wind in Europe doesn't mean no wind risk, because
  windstorms aren't covered.
- **Surface water flood:** there's no data for this in the default setup, so it shows "No data".
- **"No vulnerability":** physrisk has no damage model for this hazard and building type, which is
  different from low risk.
- **Zero:** river flood at zero means the exact point is dry in the data, not that the area has no
  flood risk.

## Hazard maps

The asset panel can show a map around the asset, drawn from physrisk's own map data. It answers
where the flood plain is, which a single point's numbers can't. Read it with these limits:

- **Only river and coastal flood.** physrisk's maps of wind, fire, hail, heat and drought aren't
  public, so these hazards are listed but can't be chosen.
- **Only the 1-in-1000-year flood.** The maps hold no other return period. The table above the map
  has the depths for the other return periods at the exact point.
- **About 1 km pixels**, so the map shows the area, not the building. It stops adding detail past a
  regional zoom.
- **Before flood protection.** Like the river flood curve, and unlike the loss figures, the map
  ignores defences.
- **"Historical" is physrisk's baseline**, which for these maps is its RCP4.5 2030 data, the same
  data the assessment uses. physrisk has flood maps for SSP2-4.5 and SSP5-8.5 from 2030 to 2080
  only, and none for SSP1-2.6 or SSP3-7.0.
- **A clear area means no flood in the data**, not no flood risk.

**Use it to** screen many sites and find which deserve a closer look. **Don't use it for** decisions
about a single site, or for currency estimates of loss.
