# Plate Trail

A privacy-audit tool that measures what a history of automated license plate
reader (ALPR) reads could reveal about a driver, using only public camera
locations and synthetic drivers. See
[the proposal](KTP-Capstone-Proposal-Plate-Trail.md).

Setup instructions, ethics statement, and build status are added as the
project is built.

## Quick start (development)

Requires Docker. PostGIS is published on host port **5434** (override with
`PLATETRAIL_DB_PORT`) to avoid clashing with other local Postgres instances.

```bash
docker compose up -d --build      # db :5434, api :8000, web :3000
curl localhost:8000/health
```

Backend tests locally (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up -d db
DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail .venv/bin/pytest
```

Tests marked `db` are skipped when `DATABASE_URL` is unset. CI always runs them
against a PostGIS service container.

## Camera ETL

```bash
cd backend
DATABASE_URL=postgresql+psycopg://platetrail:platetrail@localhost:5434/platetrail \
  .venv/bin/python -m platetrail.etl.run_etl            # add --refresh to refetch
```

Pulls ALPR cameras (`man_made=surveillance` + `surveillance:type=ALPR`) for
Edison and New Brunswick from OpenStreetMap via Overpass. Raw responses are
cached in `data/raw/overpass/`, so reruns don't hit Overpass. Direction comes
from `camera:direction`, falling back to `direction`. When both are present and
disagree, the summary lists the camera. New sources plug in as additional
`CameraLoader`s and go through the same deduplication step.
