"""API response models. The front end's types are generated from these: see script/export_openapi.py
and /sync-generated.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class RunStatus(BaseModel):
    run_id: str
    source_name: str | None
    total_rows: int
    status: str  # queued | running | completed | failed | interrupted
    stage: str | None  # geolocating | classifying | flood_zones | assessing
    done: int  # progress within the stage
    total: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    queue_position: int | None  # 1 is next; None when not waiting


class Exclusion(BaseModel):
    reason: str  # invalid | off_land | no_curve
    assets: int


class Summary(BaseModel):
    total_assets: int
    assessable: int
    excluded: int
    assumed_type: int
    global_curve: int
    nearest_match: int
    no_building: int
    failed_assets: int
    exclusions: list[Exclusion]
    shared_hazards: list[str]


class Asset(BaseModel):
    row_num: int
    asset_id: str | None  # a row with no id is reported as invalid, so row_num is the key
    lat: float | None
    lon: float | None
    match_type: str  # intersects | nearest | none | invalid
    distance_m: float | None
    building_id: str | None
    name: str | None
    class_: str | None = Field(alias="class")
    subtype: str | None
    height: float | None
    num_floors: int | None
    region: str | None
    region_source: str | None
    physrisk_type: str | None
    physrisk_location: str | None
    location_fallback: bool | None
    type_source: str | None  # class | subtype | assumed
    assessable: bool | None
    exclusion_reason: str | None
    # FEMA flood zone at the point. fema_status says why there's none: not_mapped (in the US but
    # on no FEMA map), not_us, not_located or unavailable (no FEMA data for this run).
    fema_status: str  # mapped | not_mapped | not_us | not_located | unavailable
    fema_zone: str | None  # FLD_ZONE as FEMA publishes it
    fema_zone_subtype: str | None
    fema_zone_key: str | None  # a key in /flood-zone-definitions; Zone X is split by shading
    in_sfha: bool | None  # None when FEMA's data doesn't say
    base_flood_elevation: float | None
    base_flood_elevation_unit: str | None
    base_flood_elevation_datum: str | None
    fema_depth: float | None  # AO zones give a depth instead of an elevation
    fema_depth_unit: str | None
    fema_dfirm_id: str | None
    fema_matches: int  # FEMA polygons covering the point; the highest-risk zone is shown
    fema_conflict: bool  # those polygons disagree on the zone


class Cluster(BaseModel):
    """A DBSCAN group of nearby assets. Noise assets are in no cluster."""

    cluster_id: int
    assets: int
    row_nums: list[int]
    lat: float  # centre
    lon: float
    bounds: list[float]  # west, south, east, north; east is past 180 across the antimeridian


class AssetImpact(BaseModel):
    scenario: str
    year: int | None  # None is the historical baseline
    hazard: str
    impact_type: str
    aal: float | None
    aal_std: float | None
    hazard_paths: list[str]


class AssetScore(BaseModel):
    scenario: str
    year: int | None
    hazard: str
    score: int
    label: str | None


class AssetDetail(Asset):
    geometry_wkt: str | None
    fema_map_as_of: date | None  # when the FEMA data was published or downloaded
    impacts: list[AssetImpact]
    scores: list[AssetScore]


class Impact(BaseModel):
    row_num: int
    asset_id: str | None
    lat: float | None
    lon: float | None
    hazard: str
    impact_type: str
    aal: float | None
    aal_std: float | None


class AssetTotal(BaseModel):
    row_num: int
    asset_id: str | None
    total_aal: float | None
    shared_aal: float | None  # over hazards in every scenario: use this to compare scenarios
    hazards: int


class Score(BaseModel):
    row_num: int
    asset_id: str | None
    hazard: str
    score: int
    label: str | None


class TrajectoryPoint(BaseModel):
    scenario: str
    year: int | None
    assets: int
    mean_total_aal: float | None
    mean_shared_aal: float | None
    hazards: int


class Coverage(BaseModel):
    scenario: str
    year: int | None
    hazard: str
    assets: int
    covered: bool
    shared: bool


class HazardCurve(BaseModel):
    return_periods: list[float]
    intensities: list[float]


class HazardMapLayer(BaseModel):
    hazard: str
    available: bool
    reason: str | None  # why there's no map for this scenario and year
    return_period: int
    units: str
    min_value: float
    max_value: float
    max_zoom: int
    legend: list[str]  # CSS colours from min_value to max_value, as drawn on the map
    tile_url: str | None  # {z}, {x} and {y} are left for the map to fill in


class Source(BaseModel):
    title: str
    url: str


class FloodZoneDefinition(BaseModel):
    key: str  # what fema_zone_key holds
    fld_zone: str
    risk_rank: int  # 1 is the highest risk; it decides between overlapping polygons
    label: str
    risk: str  # high | moderate | minimal | undetermined | not_applicable
    annual_chance: str
    sfha: bool | None  # whether FEMA counts the zone as a Special Flood Hazard Area
    insurance: str  # a key in insurance: required | not_required | not_applicable
    summary: str
    sources: list[Source]


class InsuranceRule(BaseModel):
    key: str
    label: str
    text: str
    sources: list[Source]


class FloodZoneStatus(BaseModel):
    key: str  # a fema_status other than mapped
    label: str
    summary: str


class FloodZoneDefinitions(BaseModel):
    zones: list[FloodZoneDefinition]
    insurance: list[InsuranceRule]
    statuses: list[FloodZoneStatus]


class AppConfig(BaseModel):
    scenarios: list[str]
    years: list[int]
    default_building_type: str
    max_portfolio_rows: int
    max_upload_mb: float


class Health(BaseModel):
    status: str
