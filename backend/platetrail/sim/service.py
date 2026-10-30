"""The process-wide simulation runner, shared by the API and the Celery worker.

The road graph and cameras load once per process, on first use. Tests can
swap in a different runner with set_runner().
"""

import threading

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

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


def get_study_runner() -> SimulationRunner | None:
    """The shared runner if the study's data is ready, else None. Unlike get_local_runner this never
    downloads the road graph, so the check-up works with no database or before the data steps have run."""
    with _lock:
        if _runner is not None:
            return _runner
    from platetrail.config import get_settings
    from platetrail.db import get_engine
    from platetrail.roads.graph import graph_path

    if not graph_path(get_settings().data_dir).exists():
        return None
    try:
        with get_engine().connect() as conn:
            if not conn.execute(text("SELECT EXISTS (SELECT 1 FROM cameras)")).scalar_one():
                return None
    except (OperationalError, ProgrammingError):  # no database, or one not migrated yet
        return None
    return get_local_runner()


def set_runner(runner: SimulationRunner | None) -> None:
    global _runner
    with _lock:
        _runner = runner
