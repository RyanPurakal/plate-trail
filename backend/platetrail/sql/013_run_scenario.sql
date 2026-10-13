-- Density scenario used by a run: synthetic cameras added at simulation time
-- (platetrail.sim.scenarios). NULL / no cameras = real cameras only.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS scenario jsonb;
