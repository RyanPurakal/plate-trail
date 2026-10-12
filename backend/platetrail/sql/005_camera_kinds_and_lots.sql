-- Direction ambiguity comes from the camera ETL (disagreeing direction tags).
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS alt_directions_deg double precision[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS direction_ambiguous boolean NOT NULL DEFAULT false;

-- Set by the roads step. private_lot cameras watch a parking/retail lot or
-- its driveway and have no public-road snap. snap_ambiguous marks public-road
-- cameras angled between streets, so it is unclear which one they watch.
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS camera_kind text NOT NULL DEFAULT 'public_road'
    CHECK (camera_kind IN ('public_road', 'private_lot'));
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS snap_ambiguous boolean NOT NULL DEFAULT false;

-- One row per private_lot camera. `facings` is aligned with the camera's
-- directions_deg: whether each direction points into the lot or toward the
-- public road. The facing-convention setting turns that into arrivals or
-- departures at match time. alt_facings does the same for alt_directions_deg.
CREATE TABLE IF NOT EXISTS camera_lots (
    camera_id          integer PRIMARY KEY REFERENCES cameras (id) ON DELETE CASCADE,
    lot_osm_id         text,
    lot_kind           text,           -- retail / parking / shop
    lot_name           text,
    lot_geom           geometry(Geometry, 4326),
    watched_way_osm_id text,           -- service road the camera faces along, if any
    watched_way_geom   geometry(LineString, 4326),
    facings            text[],
    alt_facings        text[],
    CHECK (facings <@ ARRAY['into_lot', 'toward_road']::text[]),
    CHECK (alt_facings IS NULL OR alt_facings <@ ARRAY['into_lot', 'toward_road']::text[])
);
