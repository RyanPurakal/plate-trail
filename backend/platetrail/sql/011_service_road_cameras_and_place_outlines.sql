-- Cameras deep inside lots and business parks (more than 50 m from any
-- public road) are snapped to the internal service streets they watch and
-- matched like road cameras: camera_kind 'service_road'.
ALTER TABLE cameras DROP CONSTRAINT IF EXISTS cameras_camera_kind_check;
ALTER TABLE cameras ADD CONSTRAINT cameras_camera_kind_check
    CHECK (camera_kind IN ('public_road', 'private_lot', 'service_road'));

-- Point used to attach a place to the road network. For very large buildings
-- whose OSM centre point is far inside the footprint, this is the point on
-- the building outline nearest the network (attach_method 'outline').
ALTER TABLE places ADD COLUMN IF NOT EXISTS attach_geom geometry(Point, 4326);
ALTER TABLE places ADD COLUMN IF NOT EXISTS attach_method text;
