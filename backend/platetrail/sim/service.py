"""The process-wide simulation runner, shared by the API and the Celery worker.

The road graph and cameras load once per process, on first use. Tests can
swap in a different runner with set_runner().
"""

import threading

from platetrail.sim.runner import SimulationRunner

_runner: SimulationRunner | None = None
_lock = threading.Lock()


def get_local_runner() -> SimulationRunner:
    global _runner
    with _lock:
        if _runner is None:
            from platetrail.db import get_engine
            from platetrail.sim.runner import LocalRunner

            _runner = LocalRunner.from_db(get_engine())
        return _runner


def set_runner(runner: SimulationRunner | None) -> None:
    global _runner
    with _lock:
        _runner = runner
