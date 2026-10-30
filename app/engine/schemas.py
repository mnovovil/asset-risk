"""API response models. The front end's types are generated from these: see script/export_openapi.py
and /sync-generated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RunStatus(BaseModel):
    run_id: str
    source_name: str | None
    total_rows: int
    status: str  # queued | running | completed | failed | interrupted
    stage: str | None  # geolocating | classifying | assessing
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


class AppConfig(BaseModel):
    scenarios: list[str]
    years: list[int]
    default_building_type: str
    max_portfolio_rows: int
    max_upload_mb: float


class Health(BaseModel):
    status: str
