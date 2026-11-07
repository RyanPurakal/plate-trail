"""Which OpenStreetMap ways count as roads for route checks.

The network is OSMnx's drive network plus service roads, except parking
aisles, drive-throughs, emergency access and private roads (CUSTOM_FILTER).
Service roads are needed to reach places inside large lots and business
parks. Their speed is set to SERVICE_SPEED_KPH, and the router penalizes them
for through traffic (sim.routing) so routes don't cut through lots.
"""

# OSMnx's drive_service filter, additionally excluding parking aisles and drive-throughs.
CUSTOM_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|footway|no|'
    'path|pedestrian|planned|platform|proposed|raceway|razed|rest_area|services|steps|track"]'
    '["motor_vehicle"!~"no"]["motorcar"!~"no"]'
    '["service"!~"emergency_access|parking_aisle|private|drive-through|drive_through"]'
)
# ASSUMPTION: free-flow speed on service roads (lot entrances, business-park streets).
SERVICE_SPEED_KPH = 15.0
