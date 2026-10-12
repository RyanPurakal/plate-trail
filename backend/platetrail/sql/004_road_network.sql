-- Drive network edges from OSMnx (one row per directed edge; two-way roads
-- appear twice), and camera-to-edge snaps. A camera on a two-way road gets
-- one camera_edges row per direction, each with that direction's bearing.
CREATE TABLE IF NOT EXISTS road_edges (
    u               bigint NOT NULL,
    v               bigint NOT NULL,
    key             integer NOT NULL,
    osmid           text,
    name            text,
    highway         text,
    oneway          boolean,
    length_m        double precision NOT NULL,
    speed_kph       double precision,
    travel_time_s   double precision,
    geom            geometry(LineString, 4326) NOT NULL,
    PRIMARY KEY (u, v, key)
);
CREATE INDEX IF NOT EXISTS road_edges_geom_idx ON road_edges USING gist (geom);

CREATE TABLE IF NOT EXISTS camera_edges (
    camera_id        integer NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
    u                bigint NOT NULL,
    v                bigint NOT NULL,
    key              integer NOT NULL,
    snap_distance_m  double precision NOT NULL,
    edge_bearing_deg double precision NOT NULL,  -- travel bearing u->v at the snap point
    fraction_along   double precision NOT NULL,  -- 0 at u, 1 at v
    snap_geom        geometry(Point, 4326) NOT NULL,
    PRIMARY KEY (camera_id, u, v, key),
    FOREIGN KEY (u, v, key) REFERENCES road_edges (u, v, key) ON DELETE CASCADE
);
