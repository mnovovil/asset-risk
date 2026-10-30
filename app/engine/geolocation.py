"""Call the geolocate library from the vendor/geolocate submodule.

The only module that imports geolocate. It has no package install and exposes top-level modules
(`config`, `db`, `match`, `geolocate`), so its src/ folder goes on the path here and nowhere else.
Its output CSV columns are a documented stable interface, so that is what the engine consumes.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import TextIO

from engine.settings import ROOT, Settings

GEOLOCATE_SRC = ROOT / "vendor" / "geolocate" / "src"

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


class GeolocationError(Exception):
    """geolocate is missing or misconfigured, or a run failed."""


class InvalidPortfolio(GeolocationError):
    """geolocate could not read the CSV, or it lacks the required columns."""


def _module(name: str, src: Path = GEOLOCATE_SRC) -> ModuleType:
    if not (src / "geolocate.py").is_file():
        raise GeolocationError(f"{src} is empty: run `git submodule update --init`")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return importlib.import_module(name)


def read_points(csv_path: str | os.PathLike[str]) -> list[tuple[str | None, ...]]:
    """Return (id, lat, lon) rows as raw strings, in input order."""
    library = _module("geolocate")
    try:
        return library.read_points(Path(csv_path))
    except library.InputError as e:
        raise InvalidPortfolio(str(e)) from None


class _CountingFile:
    """Report rows as run() writes them: it writes once per row, and flushes after each batch."""

    def __init__(self, file: TextIO, total: int, on_progress: Progress | None) -> None:
        self._file = file
        self._total = total
        self._on_progress = on_progress
        self._rows = -1  # the first write is the header

    def write(self, line: str) -> int:
        self._rows += 1
        return self._file.write(line)

    def flush(self) -> None:
        self._file.flush()
        if self._on_progress is not None:
            self._on_progress(max(self._rows, 0), self._total)


def locate(
    points: list[tuple[str | None, ...]],
    output: str | os.PathLike[str],
    settings: Settings,
    on_progress: Progress | None = None,
) -> dict[str, int]:
    """Match points to buildings, write geolocate's output CSV and return counts by match type."""
    library = _module("geolocate")
    config = _module("config")
    try:
        cfg = config.load_config(settings.geolocate_config)
    except config.ConfigError as e:
        raise GeolocationError(str(e)) from None
    if cfg.overture_file_index is None:
        logger.warning("No file index for this release: every point scans the whole folder")

    try:
        with open(output, "w", newline="") as f:
            return library.run(
                points,
                cfg,
                _CountingFile(f, len(points), on_progress),
                settings.geolocate_workers,
                settings.geolocate_batch_size,
            )
    except Exception as e:
        raise GeolocationError(f"geolocate failed: {e}") from e
