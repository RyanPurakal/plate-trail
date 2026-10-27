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


def test_scenario_town_must_be_a_region_town():
    import pytest
    from pydantic import ValidationError

    from platetrail.api.schemas import PopulationRequestBody, SimulateRequest

    assert SimulateRequest(extra_cameras=3, scenario_town="New Brunswick").to_request().scenario_town == "New Brunswick"
    assert PopulationRequestBody(extra_cameras=3, scenario_town="Edison").to_request().scenario_town == "Edison"
    assert SimulateRequest(extra_cameras=3).to_request().scenario_town is None
    for model in (SimulateRequest, PopulationRequestBody):
        with pytest.raises(ValidationError, match="scenario_town must be one of"):
            model(extra_cameras=3, scenario_town="Nowhere")
