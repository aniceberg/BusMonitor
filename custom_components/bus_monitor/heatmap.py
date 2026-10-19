"""Route heatmap from recorded trips (pure logic).

The map is cut into small square cells. For each trip we walk its trail
(filling in between GPS fixes) and mark every cell it passed through once.
A cell's value is the share of trips that passed through it, so the usual route
scores close to 1.0 and an occasional detour scores low.
"""

from __future__ import annotations

import math
from typing import Any

from .calibration import TripRecord
from .geo import haversine_m

DEFAULT_CELL_M = 12.0
# Don't draw a straight line across a long GPS gap; just mark both ends.
MAX_FILL_GAP_S = 180


def route_heatmap(trips: list[TripRecord], cell_m: float = DEFAULT_CELL_M) -> dict[str, Any]:
    points = [p for t in trips for p in t.trail]
    if not points:
        return {"trips": 0, "cell_m": cell_m, "dlat": 0, "dlon": 0, "cells": []}
    lat0 = sum(p[1] for p in points) / len(points)
    dlat = cell_m / 111_320
    dlon = cell_m / (111_320 * math.cos(math.radians(lat0)))

    def key(lat: float, lon: float) -> tuple[int, int]:
        return math.floor(lat / dlat), math.floor(lon / dlon)

    counts: dict[tuple[int, int], int] = {}
    for trip in trips:
        seen: set[tuple[int, int]] = set()
        trail = trip.trail
        if trail:
            seen.add(key(trail[0][1], trail[0][2]))
        for (t1, la1, lo1, _), (t2, la2, lo2, _) in zip(trail, trail[1:], strict=False):
            if (t2 - t1).total_seconds() > MAX_FILL_GAP_S:
                seen.add(key(la2, lo2))
                continue
            steps = max(1, math.ceil(haversine_m(la1, lo1, la2, lo2) / (cell_m / 2)))
            for k in range(1, steps + 1):
                f = k / steps
                seen.add(key(la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f))
        for cell in seen:
            counts[cell] = counts.get(cell, 0) + 1

    n = len(trips)
    cells = [
        [round((i + 0.5) * dlat, 6), round((j + 0.5) * dlon, 6), round(c / n, 3), c]
        for (i, j), c in counts.items()
    ]
    cells.sort(key=lambda c: c[2])  # draw rare cells first, common ones on top
    return {"trips": n, "cell_m": cell_m, "dlat": dlat, "dlon": dlon, "cells": cells}
