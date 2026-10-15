"""Resolve 'which street, between which cross streets' from OSM ways (pure logic)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .geo import EARTH_RADIUS_M, angle_diff_deg, bearing_deg, distance_to_segment_m

# Beyond this the bus is not really "on" any road (parking lot, bad fix).
MAX_ON_STREET_M = 80.0


@dataclass(frozen=True)
class Way:
    id: int
    name: str
    nodes: tuple[int, ...]
    geometry: tuple[tuple[float, float], ...]  # (lat, lon) parallel to nodes


@dataclass(frozen=True)
class StreetInfo:
    street: str | None  # street the bus is on
    behind: str | None  # nearest cross street already passed
    ahead: str | None  # nearest cross street coming up
    directional: bool  # False when heading was unknown (behind/ahead is arbitrary)
    distance_m: float | None  # distance from the street centre line


def parse_overpass(data: dict[str, Any]) -> list[Way]:
    """Parse `out body geom` JSON for named highways."""
    ways = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        name = (el.get("tags") or {}).get("name")
        nodes, geom = el.get("nodes"), el.get("geometry")
        if not name or not nodes or not geom or len(nodes) != len(geom):
            continue
        ways.append(
            Way(
                id=int(el["id"]),
                name=name,
                nodes=tuple(int(n) for n in nodes),
                geometry=tuple((float(g["lat"]), float(g["lon"])) for g in geom),
            )
        )
    return ways


def _nearest_segment(
    lat: float, lon: float, ways: list[Way]
) -> tuple[Way, float, tuple[float, float, float, float]] | None:
    best = None
    for way in ways:
        for (la1, lo1), (la2, lo2) in zip(way.geometry, way.geometry[1:], strict=False):
            d = distance_to_segment_m(lat, lon, la1, lo1, la2, lo2)
            if best is None or d < best[1]:
                best = (way, d, (la1, lo1, la2, lo2))
    return best


def _local_xy(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """Metres east/north of (lat0, lon0)."""
    kx = math.cos(math.radians(lat0)) * math.pi / 180 * EARTH_RADIUS_M
    ky = math.pi / 180 * EARTH_RADIUS_M
    return (lon - lon0) * kx, (lat - lat0) * ky


def describe_position(
    lat: float, lon: float, heading: float | None, ways: list[Way]
) -> StreetInfo:
    """Name the street under the bus and the cross streets before and after it."""
    nearest = _nearest_segment(lat, lon, ways)
    if nearest is None:
        return StreetInfo(None, None, None, False, None)
    main, dist, (la1, lo1, la2, lo2) = nearest
    street = main.name

    # Direction of travel along the street: the segment direction closest to heading.
    seg_bearing = bearing_deg(la1, lo1, la2, lo2)
    directional = heading is not None
    axis = seg_bearing
    if heading is not None and angle_diff_deg(seg_bearing, heading) > 90:
        axis = (seg_bearing + 180) % 360
    ax, ay = math.sin(math.radians(axis)), math.cos(math.radians(axis))

    # OSM splits a street into many ways at junctions, so use every way with this name.
    main_ways = [w for w in ways if w.name == street]
    other_ways = [w for w in ways if w.name != street]
    node_names: dict[int, set[str]] = {}
    for w in other_ways:
        for n in w.nodes:
            node_names.setdefault(n, set()).add(w.name)

    ahead: tuple[float, str] | None = None
    behind: tuple[float, str] | None = None
    seen: set[int] = set()
    for w in main_ways:
        for node, (nla, nlo) in zip(w.nodes, w.geometry, strict=True):
            if node in seen or node not in node_names:
                continue
            seen.add(node)
            x, y = _local_xy(lat, lon, nla, nlo)
            along = x * ax + y * ay
            # Skip junctions on a distant branch of the same street: the cross street
            # must be reasonably close to the bus.
            if math.hypot(x, y) > 800:
                continue
            name = sorted(node_names[node])[0]
            if along >= 0 and (ahead is None or along < ahead[0]):
                ahead = (along, name)
            elif along < 0 and (behind is None or -along < behind[0]):
                behind = (-along, name)

    return StreetInfo(
        street=street,
        behind=behind[1] if behind else None,
        ahead=ahead[1] if ahead else None,
        directional=directional,
        distance_m=dist,
    )
