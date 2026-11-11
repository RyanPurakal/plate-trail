-- Distance from each place to the nearest drive-network edge. Places beyond
-- the router's attachment limit are kept out of the sampling pool.
ALTER TABLE places ADD COLUMN IF NOT EXISTS network_distance_m double precision;
