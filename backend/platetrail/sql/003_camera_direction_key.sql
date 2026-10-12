-- Which tag the direction value came from, and manufacturer as a first-class
-- column (it was previously only inside tags).
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS direction_key text;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS manufacturer text;
ALTER TABLE camera_source_records ADD COLUMN IF NOT EXISTS direction_key text;
