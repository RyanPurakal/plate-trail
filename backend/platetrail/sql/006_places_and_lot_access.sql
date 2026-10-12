-- Study-area town boundaries (from OSM relations) and candidate anchor places.
CREATE TABLE IF NOT EXISTS towns (
    name      text PRIMARY KEY,
    osm_id    text NOT NULL,
    geom      geometry(MultiPolygon, 4326) NOT NULL
);

-- Places that routines can visit. Homes are not stored here: they are
-- sampled along residential streets (see routines.places).
CREATE TABLE IF NOT EXISTS places (
    id           serial PRIMARY KEY,
    osm_id       text NOT NULL UNIQUE,
    category     text NOT NULL,   -- grocery, retail, food, services, leisure, worship, work, university, hospital, industrial
    subcategory  text,            -- the OSM tag value, e.g. supermarket
    name         text,
    town         text REFERENCES towns (name),
    geom         geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS places_geom_idx ON places USING gist (geom);
CREATE INDEX IF NOT EXISTS places_category_idx ON places (category);

-- The public road a lot camera's driveway meets: the nearest drive edge to
-- the camera. A lot camera only sees trips whose lot-side edge is this road.
ALTER TABLE camera_lots ADD COLUMN IF NOT EXISTS access_u bigint;
ALTER TABLE camera_lots ADD COLUMN IF NOT EXISTS access_v bigint;
ALTER TABLE camera_lots ADD COLUMN IF NOT EXISTS access_distance_m double precision;
