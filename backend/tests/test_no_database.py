"""The check-up works with no database; the example study's endpoints say so plainly."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from platetrail import db
from platetrail.api import main
from platetrail.api.main import app
from platetrail.roads.graph import graph_path
from platetrail.sim import service


class FakeEngine:
    """Answers the study runner's "any cameras loaded?" query."""

    def __init__(self, has_cameras):
        self.has_cameras = has_cameras

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _query):
        return self

    def scalar_one(self):
        return self.has_cameras


@pytest.fixture
def no_database(monkeypatch):
    engine = create_engine("postgresql+psycopg://nobody:nobody@127.0.0.1:1/none")
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(service, "_runner", None)
    yield
    engine.dispose()


@pytest.fixture
def graph_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATETRAIL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_runner", None)
    path = graph_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


def use_engine(monkeypatch, has_cameras):
    monkeypatch.setattr(db, "get_engine", lambda: FakeEngine(has_cameras))


def test_api_starts_and_serves_the_check_up(no_database):
    with TestClient(app) as client:
        assert client.get("/region").status_code == 200


@pytest.mark.parametrize("path", ["/health", "/cameras", "/runs", "/runs/1", "/populations"])
def test_study_endpoints_explain_the_missing_database(no_database, path):
    with TestClient(app) as client:
        resp = client.get(path)
    assert resp.status_code == 503
    assert "Exploring areas and checking routes still work" in resp.json()["detail"]


def test_no_study_runner_without_a_database(no_database, graph_file):
    assert service.get_study_runner() is None


def test_no_study_runner_or_download_without_a_built_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATETRAIL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_runner", None)
    use_engine(monkeypatch, True)
    monkeypatch.setattr(service, "get_local_runner", lambda: pytest.fail("would build the study graph"))
    assert service.get_study_runner() is None


def test_no_study_runner_before_cameras_are_loaded(graph_file, monkeypatch):
    use_engine(monkeypatch, False)
    monkeypatch.setattr(service, "get_local_runner", lambda: pytest.fail("would load an empty sensor list"))
    assert service.get_study_runner() is None


def test_study_runner_loads_once_its_data_is_there(graph_file, monkeypatch):
    use_engine(monkeypatch, True)
    monkeypatch.setattr(service, "get_local_runner", lambda: "runner")
    assert service.get_study_runner() == "runner"


def test_loaded_runner_needs_no_new_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATETRAIL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_runner", "loaded")
    assert service.get_study_runner() == "loaded"
