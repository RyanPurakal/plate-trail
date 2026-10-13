-- Population runs: many synthetic drivers under one configuration, for
-- unicity and policy analysis. Reads are stored compactly; per-driver trips
-- are not (they are reproducible from the config and seed).
CREATE TABLE IF NOT EXISTS populations (
    id              serial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    status          text NOT NULL DEFAULT 'complete',
    drivers         integer NOT NULL,
    weeks           integer NOT NULL,
    start_date      date NOT NULL,
    seed            bigint NOT NULL,
    generator       text NOT NULL,
    match_config    jsonb NOT NULL,
    noise_config    jsonb NOT NULL,
    scenario        jsonb,
    camera_snapshot timestamptz,
    summary         jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS population_drivers (
    population_id   integer NOT NULL REFERENCES populations (id) ON DELETE CASCADE,
    driver_idx      integer NOT NULL,
    persona         text NOT NULL,
    plate_state     text NOT NULL,
    plate           text NOT NULL,
    anchors         jsonb NOT NULL,
    trips           integer NOT NULL,
    reads           integer NOT NULL,
    PRIMARY KEY (population_id, driver_idx)
);

-- Local NJ wall-clock time, like reads.time.
CREATE TABLE IF NOT EXISTS population_reads (
    population_id   integer NOT NULL REFERENCES populations (id) ON DELETE CASCADE,
    driver_idx      integer NOT NULL,     -- ground truth: which driver produced the read
    camera_label    text NOT NULL,
    time            timestamp NOT NULL,   -- as recorded (jittered)
    plate_state     text NOT NULL,
    plate           text NOT NULL,        -- as recorded (possibly misread)
    misread         boolean NOT NULL
);
CREATE INDEX IF NOT EXISTS population_reads_pop_idx ON population_reads (population_id);
