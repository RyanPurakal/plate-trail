-- When the camera ETL last loaded cameras at the time a run was simulated.
-- Reloading cameras renumbers them, so a run is stale once this no longer
-- matches max(cameras.loaded_at). Runs from before this column are stale.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS camera_snapshot timestamptz;
