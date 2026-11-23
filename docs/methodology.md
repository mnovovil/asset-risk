# Methodology

How a coordinate becomes a risk figure, and how far to trust it. Start with the
[README](../README.md) for setup.

## From a point to a result

1. **Building.** geolocate finds the Overture building the point is inside, or the nearest one within
   100 m.
2. **Type.** The building's Overture `class` or `subtype` picks one of physrisk's building types:
   Residential, Commercial or Industrial.
3. **Region.** The point's continent picks the regional version of the damage curve.
4. **FEMA flood zone.** For points in the US and its territories, the
   [FEMA flood zone](#fema-flood-zones) at the point is looked up separately. It doesn't feed into
   physrisk's results.
5. **Assessment.** physrisk looks up each hazard at the point, turns its intensity into damage with a
   vulnerability curve, and returns the results.

## What the figures mean

**Average annual loss (AAL)** is the expected damage per year, as a share of asset value. A value of
0.5% means physrisk expects damage worth 0.5% of the asset per year on average. It isn't a forecast
for any one year.

An asset's **total** adds its hazards together.

The **portfolio mean** is equal-weighted by default: every asset with a result counts the same, so a
small shed counts as much as a large factory. A list of only `id, lat, lon` can't do better, because it
has no asset values.

### Weighting by value

If the CSV has a `value` column (see [Portfolio CSV](reference.md#portfolio-csv)), the dashboard
offers **Weighting: By value** as well.

- **Expected annual loss** is AAL times the asset's value, in the file's currency. An asset worth
  €10M with an AAL of 0.5% has an expected annual loss of €50,000. Without a `currency` column the
  amounts are plain "value units", never money.
- **The value-weighted mean** is the sum of every asset's expected loss divided by the sum of their
  values. A large asset moves it more than a small one.
- **Value-weighted figures cover only assets with both a result and a usable value.** A blank,
  negative or unreadable value leaves the asset in the run, assessed as usual, and out of these
  figures only. Each one says how many assets and how much value it covers. If few assets have a
  value, read the weighted figures as describing those assets, not the portfolio.
- Equal weighting stays the default, and the Portfolios page and the map's bubbles always use it, so
  portfolios can be compared whether or not they have values.
- Values are taken as given. The app doesn't convert currencies, and a file can use only one.
- Change over time compares scenarios on shared hazards in both weightings, and the historical
  markers are weighted the same way as the figure they sit beside.

**Scores** are physrisk's bands of AAL, from "Very low impact" to "Very high impact". Thresholds
differ by hazard group.

**The historical baseline** comes from physrisk's own historical data.

### Today (baseline)

Choosing **Today (baseline)** in the Scenario filter shows the historical baseline on its own, as
present-day risk, on the map, the headline figures, the loss bars and the table.

- physrisk treats the baseline as the year **2025**, but asking a scenario for 2025 returns scores
  and no losses, without an error. The settings only accept 2030, 2050 and 2080, so present-day risk comes from this baseline only. The Year filter
  also hides any year with no results, as older runs that asked for 2025 have.
- It isn't always observed data. For flood it's physrisk's RCP4.5 2030 data, the same as the hazard
  maps use.
- physrisk **scores scenarios only**, so the baseline has annual losses but no scores. The table shows
  each hazard's loss, and the map can only be coloured by total loss.
- Its total covers the baseline's own hazards, which can be more than some scenarios have. Compare it
  with a scenario only through the historical markers, which use the scenario's hazards.

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

- **Change over time** uses only the hazards every scenario has, and names them. SSP1-2.6 and
  SSP2-4.5 share none, so a run with both has nothing to show there. The default, SSP2-4.5 and
  SSP5-8.5, shares river flood, coastal flood and wind.
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

For total loss, and for expected annual loss when the portfolio has values, the five colours are
**quintiles**: each holds about a fifth of the assets with a
result, for the selected scenario and year. One extreme loss then only moves the top class, instead
of pushing every other asset into the lowest one. The legend gives the range of losses in each
colour. The colour shows an asset's rank within this portfolio, so the same loss can be a different
colour in another portfolio or scenario. Hazard scores keep physrisk's fixed bands.

Colouring by expected annual loss draws an asset with no usable value hollow, as one with no result,
never as a low loss. A bubble's colour is then the plain mean of its members' expected losses.

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

## The analyst

When it's turned on, a finished portfolio's page has an **Ask the analyst** chat. A local model
(`qwen3:1.7b` by default) answers questions about that run by calling read-only tools, which return the
same figures the dashboard shows. It can't see the database, other runs or the internet.

**It can tell you** what the run's results say:
- portfolio means for a scenario and year, overall or by hazard
- which assets have the highest loss
- one asset's building, type, FEMA zone, value and results
- how two scenarios compare on the hazards they share
- which assets were excluded or failed, and why

**It can't tell you** anything the results don't hold:
- risk at a place the run didn't assess
- hazards physrisk doesn't model, such as European windstorms
- what a loss means for a decision

It has the model's limits, listed above, and adds a small model's own. It can misread a question,
pick the wrong scenario or reason badly. Read its sources, not just its answer.

**"Verified" means the numbers match, not that the reasoning is right.** Every number in an answer
is checked in code against the tool results the answer cites. A number passes if one of those
results rounds to it at the precision shown, with a fraction shown as a percentage. An answer with a
number that doesn't match is marked **Unverified figures**, and lists them. A verified answer can
still compare the wrong things, or draw a conclusion the figures don't support.

Its instructions say:
- Figures are percentages of asset value per year.
- Portfolio figures are equal-weighted unless it says "value-weighted".
- A low score, "No model" and "No data" aren't low risk.
- Excluded and failed assets have no result, not zero loss.
- Scenarios are compared only on the hazards they share.
- It should say when a building type was assumed.
- A FEMA status without information isn't Zone X.

The checks above hold whether or not it follows these.

## FEMA flood zones

For a point in the US or one of its territories, the asset panel and the CSV export show the FEMA
flood zone the point falls in, from FEMA's National Flood Hazard Layer. Expand "What does Zone … mean?"
on the panel for the zone's meaning, its chance of flooding each year, whether flood insurance is
required, and FEMA's sources.

**A FEMA zone isn't a modelled loss.** It's the regulatory flood map that decides whether lenders must
require flood insurance. It can disagree with physrisk's river and coastal flood: physrisk reads a
1 km grid at the exact point, while FEMA draws boundaries around the 1% (100-year) flood. A point can
be dry in physrisk's data and inside a FEMA high-risk area, or the reverse. Read the two side by
side, not one as a check on the other.

How the zone is found, and how to read it:

- **Only the point.** The zone is looked up at the coordinates, not over the building's footprint.
  FEMA's own determination is for the building, which may reach into a riskier zone.
- **The highest-risk zone wins an overlap.** FEMA's data has maps from different studies over the
  same ground, and neighbouring areas meet on a line. When several areas cover the point, the panel
  shows the highest-risk one and warns that they disagree. The order puts coastal (V) zones first,
  then the other 1% zones, then open water, D, shaded X, X and unshaded X, then areas not included.
- **No zone is not low risk.** "Not on a FEMA flood map" means no FEMA area in the data covers the
  point. That's different from Zone X (mapped, moderate or minimal risk) and from Zone D (mapped,
  hazard not determined).
- **Shaded and unshaded Zone X are kept apart.** Only FEMA's subtype tells them apart. Shaded is
  moderate risk, unshaded is minimal, and minimal isn't none.
- **A missing base flood elevation** often means FEMA drew it as lines along the river, which this
  data doesn't include, not that there's none.
- **"High-risk area (SFHA)"** is FEMA's own flag for the area. In a few areas it disagrees with what
  the zone usually means, and the panel says so.
- **A snapshot.** The data is as of the date shown with the zone. FEMA's live maps change as studies
  are updated, and some locations already differ (see
  [Data sources](data-sources.md#checking-against-femas-map)).

**It's not an official determination.** Check an address that matters on
[FEMA's Flood Map Service Center](https://msc.fema.gov/portal/search).

## PDF report

**Download report as PDF** saves what the dashboard shows for the selected scenario, year, map
colouring and weighting. When the portfolio has values, it says which weighting it uses and, for
value weighting, which assets the figures cover. It has the headline figures with where building types came from, the risk map with its
legend, annual loss by hazard and change over time, and notes taken from this page.

- The map is the view the dashboard opens with, not wherever it was panned or zoomed. It's drawn
  again at about 290 dpi, always in the light theme.
- The charts are the dashboard's own, kept as vectors, so they stay sharp when zoomed.
- If the map tiles don't load, there's no report, rather than a map with gaps that passes for a
  complete one.
- It uses A4, or US Letter where the browser's region uses it.

## An asset over time

The asset panel's **Over time** chart shows one asset's annual loss or score for one hazard, picked
from a list, across every year and scenario of the run. Read it with these limits:

- **Losses are compared hazard by hazard.** Each line is one scenario's loss for the chosen hazard,
  so lines for different scenarios can be compared directly. The dashed flat line is today's
  baseline, for reference.
- **A missing result is a gap, not zero.** A scenario with nothing for the hazard has no line, and
  the panel names it. Hazards differ by scenario, so this is common.
- **Scores have no baseline**, because physrisk scores scenarios only. They are steps from Very low
  to Very high, not measurements. "No model", "No data" and "Error" are listed under the chart, not
  drawn, and a low score isn't proof of low risk.

## Hazard maps

The asset panel can show a map around the asset. It answers where the flood plain is, or where
wildfire, tropical cyclones, large hail or drought are likely, which a single point's numbers can't. **Open larger map** opens the same map,
hazard and period full-size in a new tab. Each map's legend, no-data key and note come from the
layer itself. Read it, at any size, with these limits:

- **Only river flood, coastal flood, wildfire, tropical cyclone wind, hail and drought.**
  physrisk's maps of heat aren't public, so heat is listed but can't be chosen. The
  `hazard_map_layers` setting can turn maps off.
- **A clear area means no data**, not no risk: no flood in the flood maps, ocean or no data in the
  wildfire map, no tropical cyclone in the wind map, and no data (most open ocean, and Antarctica)
  in the hail map, and open water (or, rarely, no months below the threshold) in the drought map.

### Flood

- **Only the 1-in-1000-year flood.** The maps hold no other return period.
- **About 1 km pixels**, so the map shows the area, not the building. It stops adding detail past a
  regional zoom.
- **Before flood protection.** Unlike the loss figures, the map ignores defences.
- **"Historical" is physrisk's baseline**, which for these maps is its RCP4.5 2030 data, the same
  data the assessment uses. physrisk has flood maps for SSP2-4.5 and SSP5-8.5 from 2030 to 2080
  only, and none for SSP1-2.6 or SSP3-7.0.

### Wildfire

The app draws this map itself from Jupiter Intelligence's fire probability data, the same data
physrisk's wildfire damage figures use. physrisk won't draw it, because the data isn't in its
public group. The app reads the array anonymously from physrisk's public bucket instead.

- **The value is the highest monthly chance in the year of a wildfire within 100 km**, not at the
  building. 0.7 means a 70% chance.
- **The map and the losses aren't on the same scale.** physrisk divides this value by 500 before it
  works out damage, as a stand-in for a building-level chance, until higher-resolution data exists.
- **About 28 km pixels** (0.25°), drawn as blocks, so the map shows the region, not the property.
- **Only SSP1-2.6 and SSP5-8.5**, for 2020, 2030, 2040, 2050, 2075 and 2100. Of this app's years,
  that's 2030 and 2050. There's **no historical baseline**, so Historical has no wildfire map. The
  app never shows a nearby year or 2020 instead.
- **A low or empty area is not proof of low risk.** Cells with no data are clear, and kept apart
  from 0, which is a real value in the data and drawn in the lightest colour.
- **Source:** Jupiter Intelligence, via OS-Climate physrisk, which lists its licence as
  "Commercial".

### Tropical cyclone wind

The app draws this map itself from IRIS, the Imperial College Storm Model, which is the same data
physrisk's wind losses use. It reads the array anonymously from physrisk's public bucket.

- **The value is the 1-minute sustained wind speed that tropical cyclones reach about once in 100
  years**, in m/s. physrisk works out damage from every return period, 10 to 1000 years, so the map
  is one slice of what the losses use. It's on the same scale, though: physrisk doesn't adjust it.
- **Tropical cyclones only.** IRIS has no other windstorms, so a clear area, such as most of Europe,
  has no wind loss either. That's a gap in the data, not proof of no wind risk.
- **About 10 km pixels** (0.1°), drawn as blocks, from 60° N to 60° S.
- **Historical, and 2050 for SSP2-4.5 and SSP5-8.5.** physrisk estimates 2030 and 2080 from the
  baseline and 2050, and the map doesn't, so those years show a reason instead of a map. There's no
  SSP1-2.6 data. The app never shows a nearby year instead.
- **A low or empty area is not proof of low risk.**
- **Source:** IRIS (Sparks and Toumi), via OS-Climate physrisk, under CC BY 4.0.

### Hail

The app draws this map itself from Jupiter Intelligence's large-hail data, which is the same data
physrisk's hail losses use. It reads the array anonymously from physrisk's public bucket.

- **The value is the number of days a year when hail over 5 cm across is possible**, the mean of
  several bias-corrected, downscaled climate models. These are potential days: physrisk counts about
  1 in 50 of them as a damaging hail day, and a generic building loses 0.1% of its value on each. So
  the map is on the scale physrisk reads, but most of the days it shows cause no loss.
- **About 28 km pixels** (0.25°), drawn as blocks, so the map shows the region, not the property.
  Local hotspots are averaged away: Denver, known for hail, is close to 0.
- **Only SSP1-2.6 and SSP5-8.5**, for 2020, 2030, 2040, 2050, 2075 and 2100. With the default
  scenarios (SSP2-4.5 and SSP5-8.5) and years, only SSP5-8.5 2030 and 2050 have a map. There's no
  SSP2-4.5 data, and physrisk has no hail losses for it either.
- **No historical baseline map.** physrisk's baseline hail losses use its SSP1-2.6 2020 data, as a
  stand-in, but the app doesn't map that as Historical. physrisk estimates 2080 from 2075 and 2100,
  and the map doesn't, so 2080 shows a reason instead of a map. The app never shows a nearby year.
- **A clear area has no data**, mostly open ocean and Antarctica, and physrisk counts it as no hail
  loss. Land always has a value, and 0 is a real value, drawn in the lightest colour.
- **A low or empty area is not proof of low risk.**
- **Source:** Jupiter Intelligence, via OS-Climate physrisk, which lists its licence as
  "Commercial".

### Drought

The app draws this map itself from OS-Climate's drought indicator, the 12-month SPEI data that
physrisk's drought model reads. It reads the array anonymously from physrisk's public bucket.

- **The value is how many months a year the 12-month Standardized Precipitation Evapotranspiration
  Index is below −2**, "extreme drought" on the SPEI scale. It's a 20-year mean, across several
  climate models (`multi_model_0`, the combination physrisk picks).
- **physrisk models no drought loss for buildings.** Its only drought model is for disruption to
  manufacturing, which starts at SPEI −2. So the map shows the hazard, while the results show
  "No model" for drought, not a low score.
- **Every default scenario and year has a map**: SSP2-4.5 and SSP5-8.5 for 2030, 2050 and 2080, and
  a 2005 baseline (SSP1-2.6 too). There's no SSP3-7.0.
- **The baseline is much milder than the projections.** SPEI is measured against the past climate,
  so months below −2 are rare in 2005 and common later in drying regions.
- **A clear area is open water**, which the data stores as 0, so the app draws every 0 clear. A
  land cell with no months below −2 is also clear, but that's rare.
- **About 28 km pixels** (0.25°), drawn as blocks, from 90° N to 60° S, so the map shows the region,
  not the property.
- **A low or empty area is not proof of low risk.**
- **Source:** OS-Climate physrisk's drought indicators. physrisk lists no licence for them.

**Use it to** screen many sites and find which deserve a closer look. **Don't use it for** decisions
about a single site, or for currency estimates of loss.
