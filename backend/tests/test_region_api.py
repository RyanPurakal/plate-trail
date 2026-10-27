from fastapi.testclient import TestClient

from platetrail.api.main import app


def test_region_endpoint_serves_active_region():
    # No `with`: the app's lifespan (database migrations) is not needed here.
    body = TestClient(app).get("/region").json()
    assert body["id"] == "nj_edison_new_brunswick"
    assert body["towns"] == ["Edison", "New Brunswick"]
    assert body["scenario_town"] == "Edison"
    assert body["map"] == {"center": [-74.39, 40.53], "zoom": 11.6, "bounds": None}
    assert set(body["notes"]) == {"unlisted_sensors", "read_volume"}
    assert "518,797" in body["notes"]["read_volume"]
