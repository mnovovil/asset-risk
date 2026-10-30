"""HTTP API: upload a portfolio, follow its run, read its results, and serve the built front end.

Start it with script/serve.py. It has no login, so it must not be exposed beyond localhost.
"""

from __future__ import annotations

import csv
import io
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from engine import results, schemas, store
from engine.assess import HISTORICAL, hazard_curve
from engine.geolocation import GeolocationError
from engine.ingest import PortfolioError
from engine.pipeline import execute as run_pipeline
from engine.pipeline import start as start_run
from engine.queue import Execute, RunQueue
from engine.settings import ROOT, Settings, load_settings

FRONT_DIST = ROOT / "app" / "front" / "dist"
BYTES_PER_MB = 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_NAME_LENGTH = 255
INTERRUPTED_MESSAGE = "The app restarted before this run finished. Upload the portfolio again."
# A spreadsheet runs a cell that starts with one of these as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _queue(request: Request) -> RunQueue:
    return request.app.state.queue


SettingsDep = Annotated[Settings, Depends(_settings)]
QueueDep = Annotated[RunQueue, Depends(_queue)]


def _run(run_id: str, settings: SettingsDep) -> store.Run:
    run = store.find_run(settings.data_dir, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


RunDep = Annotated[store.Run, Depends(_run)]


def _finished_run(run: RunDep) -> store.Run:
    state = store.status(run)
    if state["status"] != "completed":
        raise HTTPException(409, f"This run has no results: it is {state['status']}")
    return run


FinishedRunDep = Annotated[store.Run, Depends(_finished_run)]


def _pair(run: FinishedRunDep, scenario: str, year: int | None = None) -> tuple[str, int | None]:
    if not results.pair_exists(run, scenario, year):
        raise HTTPException(404, "This scenario and year were not assessed")
    return scenario, year


PairDep = Annotated[tuple[str, "int | None"], Depends(_pair)]

router = APIRouter(prefix="/api")


def _status(run: store.Run, queue: RunQueue) -> schemas.RunStatus:
    return schemas.RunStatus(**store.status(run), queue_position=queue.position(run.run_id))


@router.get("/health")
def health() -> schemas.Health:
    return schemas.Health(status="ok")


@router.get("/config")
def config(settings: SettingsDep) -> schemas.AppConfig:
    return schemas.AppConfig(
        scenarios=list(settings.scenarios),
        years=list(settings.years),
        default_building_type=settings.default_building_type,
        max_portfolio_rows=settings.max_portfolio_rows,
        max_upload_mb=settings.max_upload_mb,
    )


@router.post("/runs", status_code=202)
def create_run(
    file: UploadFile, request: Request, settings: SettingsDep, queue: QueueDep
) -> schemas.RunStatus:
    """Check an uploaded CSV of id, lat, lon and queue a run. Problems are rejected up front."""
    limit = int(settings.max_upload_mb * BYTES_PER_MB)
    too_large = HTTPException(
        413, f"The file is larger than the {settings.max_upload_mb:g} MB limit"
    )
    # Starlette has spooled the whole body by now, so this can only stop us reading it further.
    if int(request.headers.get("content-length") or 0) > limit + COPY_CHUNK_BYTES:
        raise too_large

    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=uploads, suffix=".csv") as temporary:
        copied = 0
        while chunk := file.file.read(COPY_CHUNK_BYTES):
            copied += len(chunk)
            if copied > limit:
                raise too_large
            temporary.write(chunk)
        temporary.flush()
        # The name is kept only as a label: the file on disk has a generated name.
        source_name = Path(file.filename or "").name[:MAX_SOURCE_NAME_LENGTH] or None
        try:
            run, points = start_run(temporary.name, settings, source_name)
        except PortfolioError as e:
            raise HTTPException(422, _without_path(str(e), temporary.name)) from None
        except GeolocationError as e:
            raise HTTPException(500, str(e)) from None
    queue.submit(run, points, settings)
    return _status(run, queue)


def _without_path(message: str, path: str) -> str:
    """geolocate's messages name the file, which here is a temporary path."""
    return message.replace(f"{path} ", "The file ").replace(path, "the file")


@router.get("/runs")
def list_runs(settings: SettingsDep, queue: QueueDep) -> list[schemas.RunStatus]:
    runs = [_status(run, queue) for run in store.all_runs(settings.data_dir)]
    return sorted(runs, key=lambda r: r.created_at, reverse=True)


@router.get("/runs/{run_id}")
def get_run(run: RunDep, queue: QueueDep) -> schemas.RunStatus:
    return _status(run, queue)


@router.get("/runs/{run_id}/summary")
def get_summary(run: FinishedRunDep) -> schemas.Summary:
    return schemas.Summary(**results.summary(run))


@router.get("/runs/{run_id}/assets")
def get_assets(run: FinishedRunDep) -> list[schemas.Asset]:
    return [schemas.Asset(**row) for row in results.assets(run)]


def _asset(run: FinishedRunDep, row_num: int) -> dict:
    row = results.asset(run, row_num)
    if row is None:
        raise HTTPException(404, "Asset not found")
    return row


AssetDep = Annotated[dict, Depends(_asset)]


@router.get("/runs/{run_id}/assets/{row_num}")
def get_asset(row: AssetDep) -> schemas.AssetDetail:
    return schemas.AssetDetail(**row)


@router.get("/runs/{run_id}/assets/{row_num}/hazard-curve")
def get_hazard_curve(
    row: AssetDep, scenario: str = HISTORICAL, year: Annotated[int | None, Query()] = None
) -> schemas.HazardCurve:
    """River flood depth by return period. Empty when the scenario has no data for it."""
    if not row["assessable"]:
        raise HTTPException(409, "This asset was excluded, so it has no hazard curve")
    if scenario != HISTORICAL and year is None:
        raise HTTPException(422, "A scenario other than historical needs a year")
    try:
        return schemas.HazardCurve(**hazard_curve(row["lat"], row["lon"], scenario, year))
    except Exception as e:
        raise HTTPException(502, f"physrisk could not return a hazard curve: {e}") from e


@router.get("/runs/{run_id}/impacts")
def get_impacts(run: FinishedRunDep, pair: PairDep) -> list[schemas.Impact]:
    return [schemas.Impact(**row) for row in results.impacts(run, *pair)]


@router.get("/runs/{run_id}/totals")
def get_totals(run: FinishedRunDep, pair: PairDep) -> list[schemas.AssetTotal]:
    return [schemas.AssetTotal(**row) for row in results.totals(run, *pair)]


@router.get("/runs/{run_id}/scores")
def get_scores(run: FinishedRunDep, pair: PairDep) -> list[schemas.Score]:
    return [schemas.Score(**row) for row in results.scores(run, *pair)]


@router.get("/runs/{run_id}/trajectory")
def get_trajectory(run: FinishedRunDep) -> list[schemas.TrajectoryPoint]:
    return [schemas.TrajectoryPoint(**row) for row in results.trajectory(run)]


@router.get("/runs/{run_id}/coverage")
def get_coverage(run: FinishedRunDep) -> list[schemas.Coverage]:
    return [schemas.Coverage(**row) for row in results.coverage(run)]


def _escape_cell(value: object) -> object:
    """Text from an upload may be opened in a spreadsheet. Numbers can safely start with a minus."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _csv_lines(columns: list[str], rows: list[tuple]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_escape_cell(value) for value in row])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()


@router.get("/runs/{run_id}/export.csv")
def export_csv(run: FinishedRunDep) -> StreamingResponse:
    columns, rows = results.export_rows(run)
    return StreamingResponse(
        _csv_lines(columns, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="asset-risk-{run.run_id}.csv"'},
    )


class _SinglePageApp(StaticFiles):
    """Serve index.html for the front end's own routes, so a refresh on /runs/<id> works."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)


def _mark_interrupted(data_dir: Path) -> None:
    """Work is held in memory, so anything unfinished at startup can never finish."""
    for run in store.all_runs(data_dir):
        if store.status(run)["status"] in ("queued", "running"):
            store.set_status(run, "interrupted", error=INTERRUPTED_MESSAGE)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Give the front end one error shape: {"detail": "a readable message"}."""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in e['loc'] if part != 'body')}: {e['msg']}"
        for e in exc.errors()
    )
    return JSONResponse({"detail": problems}, status_code=422)


def create_app(
    settings: Settings | None = None,
    execute: Execute = run_pipeline,
    front_dist: Path = FRONT_DIST,
) -> FastAPI:
    """Build the app. Settings load at startup, so the schema can be exported without them."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings or load_settings()
        _mark_interrupted(app.state.settings.data_dir)
        app.state.queue = RunQueue(execute)
        app.state.queue.start()
        yield
        app.state.queue.stop()

    app = FastAPI(title="asset-risk", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)
    if front_dist.is_dir():
        app.mount("/", _SinglePageApp(directory=front_dist, html=True), name="front")
    return app
