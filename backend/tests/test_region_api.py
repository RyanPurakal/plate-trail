from fastapi.testclient import TestClient

from platetrail.api.main import app


def test_region_endpoint_serves_active_region():
    body = TestClient(app).get("/region").json()
    assert body == {"id": "nj_edison_new_brunswick", "name": body["name"],
                    "map": {"center": [-74.39, 40.53], "zoom": 11.6, "bounds": None}}


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}
