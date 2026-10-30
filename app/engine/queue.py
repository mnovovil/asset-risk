"""Run pipelines one at a time, in the order they arrive, on a background thread.

One at a time because geolocate can use about 1 GB of memory and physrisk's thread safety is
untested. Queued work lives in memory, so a restart loses it; api.py marks those runs interrupted.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable

from engine.pipeline import Points
from engine.settings import Settings
from engine.store import Run

logger = logging.getLogger(__name__)

STOP_TIMEOUT_SECONDS = 1.0

Execute = Callable[[Run, Points, Settings], bool]


class RunQueue:
    def __init__(self, execute: Execute) -> None:
        self._execute = execute
        self._waiting: deque[tuple[Run, Points, Settings]] = deque()
        self._condition = threading.Condition()
        self._stopped = False
        self._thread = threading.Thread(target=self._work, name="run-queue", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Stop after the current run. Don't wait long for it: it may take many minutes."""
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        self._thread.join(STOP_TIMEOUT_SECONDS)

    def submit(self, run: Run, points: Points, settings: Settings) -> None:
        with self._condition:
            self._waiting.append((run, points, settings))
            self._condition.notify_all()

    def position(self, run_id: str) -> int | None:
        """Place in the queue, where 1 is next, or None if the run isn't waiting."""
        with self._condition:
            for place, (run, _, _) in enumerate(self._waiting, 1):
                if run.run_id == run_id:
                    return place
        return None

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._waiting and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                run, points, settings = self._waiting.popleft()
            try:
                self._execute(run, points, settings)
            except Exception:  # execute records failures itself; this keeps the queue alive
                logger.exception("Run %s failed unexpectedly", run.run_id)
