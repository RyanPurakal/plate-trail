-- Canonical cameras after deduplication, plus every source record that fed
-- them (kept so cross-source agreement can be audited later).
CREATE TABLE IF NOT EXISTS cameras (
    id              serial PRIMARY KEY,
    geom            geometry(Point, 4326) NOT NULL,
    town            text NOT NULL,
    directions_deg  double precision[],          -- NULL when no usable direction
    has_direction   boolean NOT NULL,
    direction_raw   text,                         -- original tag value, for auditing
    source          text NOT NULL,                -- source of the primary record
    source_id       text NOT NULL,
    sources         text[] NOT NULL,              -- all sources that reported it
    tags            jsonb NOT NULL DEFAULT '{}',
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id),
    CHECK (has_direction = (directions_deg IS NOT NULL AND cardinality(directions_deg) > 0))
);
CREATE INDEX IF NOT EXISTS cameras_geom_idx ON cameras USING gist (geom);

CREATE TABLE IF NOT EXISTS camera_source_records (
    id              serial PRIMARY KEY,
    camera_id       integer NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
    source          text NOT NULL,
    source_id       text NOT NULL,
    geom            geometry(Point, 4326) NOT NULL,
    directions_deg  double precision[],
    direction_raw   text,
    tags            jsonb NOT NULL DEFAULT '{}',
    UNIQUE (source, source_id)
);
