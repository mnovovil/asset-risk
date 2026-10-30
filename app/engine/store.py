"""One DuckDB file per run, at <data_dir>/runs/<uuid>/run.duckdb."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

SQL_DIR = Path(__file__).parent / "sql"
GEOLOCATED_CSV = "geolocated.csv"
DATABASE = "run.duckdb"


@dataclass
class _OpenDatabase:
    connection: duckdb.DuckDBPyConnection
    users: int = 0


_open: dict[Path, _OpenDatabase] = {}
_open_lock = threading.Lock()


@dataclass(frozen=True)
class Run:
    run_id: str
    directory: Path

    @property
    def geolocated_csv(self) -> Path:
        return self.directory / GEOLOCATED_CSV

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """A cursor on the run's database, which stays open while anything is using it.

        The API reads a run while the queue's thread writes to it. Opening a file while another
        thread closes it fails in DuckDB ("Unique file handle conflict"), so one shared connection
        per file is opened and closed under a lock, and each caller gets its own cursor from it.
        """
        path = self.directory / DATABASE
        with _open_lock:
            if path not in _open:
                _open[path] = _OpenDatabase(duckdb.connect(path))
            database = _open[path]
            database.users += 1
        try:
            with database.connection.cursor() as cursor:
                yield cursor
        finally:
            with _open_lock:
                database.users -= 1
                if database.users == 0:
                    database.connection.close()
                    del _open[path]


def create_run(
    data_dir: str | os.PathLike[str], total_rows: int, source_name: str | None = None
) -> Run:
    """Create the run's folder and database. The folder name never comes from user input."""
    run_id = str(uuid.uuid4())
    directory = Path(data_dir) / "runs" / run_id
    directory.mkdir(parents=True)
    run = Run(run_id, directory)
    with run.connect() as con:
        con.execute((SQL_DIR / "schema.sql").read_text())
        con.execute((SQL_DIR / "views.sql").read_text())
        con.execute(
            "INSERT INTO runs (run_id, source_name, total_rows) VALUES (?, ?, ?)",
            [run_id, source_name, total_rows],
        )
    return run


def load_assets(run: Run) -> int:
    """Load the run's geolocate output into assets and return the row count."""
    with run.connect() as con:
        con.execute((SQL_DIR / "load_assets.sql").read_text(), [str(run.geolocated_csv)])
        loaded = con.execute("SELECT count(*) FROM assets").fetchone()[0]
        expected = con.execute("SELECT total_rows FROM runs").fetchone()[0]
    if loaded != expected:
        raise ValueError(f"Loaded {loaded} rows from geolocate's output, expected {expected}")
    return loaded


def find_run(data_dir: str | os.PathLike[str], run_id: str) -> Run | None:
    """Return the run with this id, or None. Only a canonical UUID ever becomes a path."""
    try:
        canonical = str(uuid.UUID(run_id))
    except ValueError:
        return None
    if canonical != run_id:
        return None
    run = Run(canonical, Path(data_dir) / "runs" / canonical)
    return run if (run.directory / DATABASE).is_file() else None


def all_runs(data_dir: str | os.PathLike[str]) -> list[Run]:
    return [
        run
        for directory in (Path(data_dir) / "runs").glob("*")
        if (run := find_run(data_dir, directory.name)) is not None
    ]


def set_status(run: Run, status: str, stage: str | None = None, error: str | None = None) -> None:
    """Record where the run is. Progress within the stage restarts at zero."""
    with run.connect() as con:
        con.execute(
            "UPDATE runs SET status = ?, stage = ?, error = ?, done = 0, total = 0, "
            "updated_at = current_timestamp",
            [status, stage, error],
        )


def set_progress(run: Run, done: int, total: int) -> None:
    with run.connect() as con:
        con.execute(
            "UPDATE runs SET done = ?, total = ?, updated_at = current_timestamp", [done, total]
        )


def status(run: Run) -> dict:
    with run.connect() as con:
        return _one_row(con, "SELECT * FROM runs")


def summary(run: Run) -> dict:
    with run.connect() as con:
        return _one_row(con, "SELECT * FROM v_portfolio_summary")


def _one_row(con: duckdb.DuckDBPyConnection, sql: str) -> dict:
    cursor = con.execute(sql)
    names = [d[0] for d in cursor.description]
    return dict(zip(names, cursor.fetchone(), strict=True))
