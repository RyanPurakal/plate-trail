-- Stored simulation runs: one synthetic driver over N weeks.
-- Ground truth (trips, every camera pass) and the noisy read log live side by
-- side; reads link to the pass that produced them.
--
-- Camera references deliberately have no foreign key to `cameras`: the camera
-- ETL replaces that table (and renumbers ids), which must not delete stored
-- runs. camera_label keeps the stable source id (e.g. node/14181989101).
--
-- Simulated times are local wall-clock time in New Jersey (America/New_York)
-- and stored as `timestamp` without time zone, exactly as simulated.

CREATE TABLE IF NOT EXISTS runs (
    id              serial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    status          text NOT NULL DEFAULT 'complete',
    generator       text NOT NULL,          -- e.g. template:commuter
    weeks           integer NOT NULL,
    start_date      date NOT NULL,
    seed            bigint NOT NULL,
    plate           text NOT NULL,          -- true plate (synthetic)
    plate_state     text NOT NULL,          -- ZZ
    match_config    jsonb NOT NULL,
    noise_config    jsonb NOT NULL,
    anchors         jsonb NOT NULL,         -- {"home": {...}, "work": {...}, ...}
    summary         jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS trips (
    id              serial PRIMARY KEY,
    run_id          integer NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    purpose         text NOT NULL,
    origin_key      text NOT NULL,
    origin_category text NOT NULL,
    dest_key        text NOT NULL,
    dest_category   text NOT NULL,
    planned_depart  timestamp NOT NULL,
    depart          timestamp NOT NULL,
    arrive          timestamp NOT NULL,
    length_m        double precision NOT NULL,
    duration_s      double precision NOT NULL,
    origin_geom     geometry(Point, 4326) NOT NULL,
    dest_geom       geometry(Point, 4326) NOT NULL,
    route_geom      geometry(LineString, 4326) NOT NULL,
    UNIQUE (run_id, seq)
);
CREATE INDEX IF NOT EXISTS trips_run_idx ON trips (run_id);

-- Every camera the route passed (ground truth), captured or not.
CREATE TABLE IF NOT EXISTS camera_passes (
    id                 serial PRIMARY KEY,
    run_id             integer NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    trip_id            integer NOT NULL REFERENCES trips (id) ON DELETE CASCADE,
    pass_seq           integer NOT NULL,    -- stable within the run; seeds the noise for this pass
    camera_id          integer NOT NULL,
    camera_label       text NOT NULL,
    time               timestamp NOT NULL,
    event              text NOT NULL,       -- road / arrival / departure
    travel_bearing_deg double precision,
    road_name          text,
    captured           boolean NOT NULL,    -- matcher decision (direction, mode)
    match_reason       text NOT NULL,
    noise_outcome      text,                -- read / missed / downtime; NULL if not captured
    UNIQUE (run_id, pass_seq),
    CHECK ((captured AND noise_outcome IS NOT NULL) OR (NOT captured AND noise_outcome IS NULL))
);
CREATE INDEX IF NOT EXISTS camera_passes_run_idx ON camera_passes (run_id);

-- The noisy read log: what the cameras reported.
CREATE TABLE IF NOT EXISTS reads (
    id              serial PRIMARY KEY,
    run_id          integer NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    read_seq        integer NOT NULL,       -- order in the read log (by recorded time)
    pass_id         integer NOT NULL UNIQUE REFERENCES camera_passes (id) ON DELETE CASCADE,
    camera_id       integer NOT NULL,
    camera_label    text NOT NULL,
    time            timestamp NOT NULL,   -- as recorded (jittered)
    plate           text NOT NULL,          -- as recorded (possibly misread)
    plate_state     text NOT NULL,
    misread         boolean NOT NULL,
    jitter_s        double precision NOT NULL,
    UNIQUE (run_id, read_seq)
);
CREATE INDEX IF NOT EXISTS reads_run_idx ON reads (run_id);

CREATE TABLE IF NOT EXISTS camera_outages (
    run_id          integer NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    camera_id       integer NOT NULL,
    camera_label    text NOT NULL,
    start_time      timestamp NOT NULL,
    end_time        timestamp NOT NULL
);
CREATE INDEX IF NOT EXISTS camera_outages_run_idx ON camera_outages (run_id);
