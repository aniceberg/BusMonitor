"""Small geodesy helpers (no Home Assistant imports)."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8
KNOTS_TO_MPS = 0.514444
MPH_TO_MPS = 0.44704


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, 0-360 degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff_deg(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings (0-180)."""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def distance_to_segment_m(
    plat: float,
    plon: float,
    alat: float,
    alon: float,
    blat: float,
    blon: float,
) -> float:
    """Distance from point P to the segment A-B in metres.

    Uses a local equirectangular projection, which is accurate to well under a
    metre over the few hundred metres between two GPS fixes.
    """
    lat0 = math.radians((alat + blat + plat) / 3)
    kx = math.cos(lat0) * math.pi / 180 * EARTH_RADIUS_M
    ky = math.pi / 180 * EARTH_RADIUS_M
    ax, ay = alon * kx, alat * ky
    bx, by = blon * kx, blat * ky
    px, py = plon * kx, plat * ky
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def interpolate(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> tuple[float, float]:
    """Linear interpolation between two nearby points."""
    return lat1 + (lat2 - lat1) * fraction, lon1 + (lon2 - lon1) * fraction


def compass(deg: float) -> str:
    """Eight-point compass name for a bearing."""
    names = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
    return names[int(((deg % 360) + 22.5) // 45) % 8]


def offset_point(lat: float, lon: float, bearing: float, distance_m: float) -> tuple[float, float]:
    """Point `distance_m` from (lat, lon) along `bearing` (fine for short distances)."""
    b = math.radians(bearing)
    dlat = distance_m * math.cos(b) / 111_320
    dlon = distance_m * math.sin(b) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon
