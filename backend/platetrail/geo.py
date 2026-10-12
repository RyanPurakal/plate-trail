"""Small geometry helpers shared by the ETL, snapping, and matching."""

from pyproj import Geod

WGS84 = Geod(ellps="WGS84")


def angle_diff(a: float, b: float) -> float:
    """Smallest difference between two bearings, in [0, 180]."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def axis_diff(a: float, b: float) -> float:
    """Difference between two undirected axes, in [0, 90]. 0 = parallel, 90 = perpendicular."""
    d = angle_diff(a, b)
    return min(d, 180.0 - d)


def geodesic_bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """True-north forward azimuth from point 1 to point 2, in [0, 360)."""
    az, _, _ = WGS84.inv(lon1, lat1, lon2, lat2)
    return az % 360.0
