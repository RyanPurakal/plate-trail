-- Lot camera access point as a junction node (where a public road meets a
-- service road) rather than an edge: a junction splits the public road into
-- two edges, and arrivals from either side end at the same node.
ALTER TABLE camera_lots ADD COLUMN IF NOT EXISTS access_node bigint;
ALTER TABLE camera_lots ADD COLUMN IF NOT EXISTS access_node_distance_m double precision;
