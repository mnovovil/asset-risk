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

**Use it to** screen many sites and find which deserve a closer look. **Don't use it for** decisions
about a single site, or for currency estimates of loss.
