-- Lot cameras are matched by entrance junction (access_node, migration 008).
-- The earlier access-edge columns are no longer used.
ALTER TABLE camera_lots DROP COLUMN IF EXISTS access_u;
ALTER TABLE camera_lots DROP COLUMN IF EXISTS access_v;
ALTER TABLE camera_lots DROP COLUMN IF EXISTS access_distance_m;
