import pytest
from fastapi.testclient import TestClient

from platetrail.api.main import app

pytestmark = pytest.mark.db


def test_health_reports_postgis():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgis"]
