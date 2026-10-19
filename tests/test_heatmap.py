from datetime import timedelta

from custom_components.bus_monitor.calibration import TripRecord
from custom_components.bus_monitor.heatmap import route_heatmap

from .conftest import MONDAY_7AM


def _trip(day: int, lons: list[float], lat_step: float = 0.0004) -> TripRecord:
    t0 = MONDAY_7AM + timedelta(days=day)
    trail = [(t0 + timedelta(seconds=15 * i), 40.0 + i * lat_step, lon, 5.0) for i, lon in enumerate(lons)]
    return TripRecord("am", t0.date().isoformat(), trail[-1][0], {}, trail)


def test_usual_route_scores_one_and_detour_scores_low():
    usual = [-75.0] * 10
    detour = [-75.0] * 3 + [-74.995] * 4 + [-75.0] * 3  # ~420 m east for a few fixes
    hm = route_heatmap([_trip(d, usual) for d in range(4)] + [_trip(4, detour)])
    assert hm["trips"] == 5
    by_frac = sorted({c[2] for c in hm["cells"]})
    assert by_frac[-1] == 1.0  # start/end shared by all trips
    assert min(by_frac) <= 0.2  # cells only the detour used
    assert any(c[2] == 0.8 for c in hm["cells"])  # usual-only cells: 4 of 5 trips


def test_gaps_are_filled_between_fixes():
    hm = route_heatmap([_trip(0, [-75.0, -75.0], lat_step=0.002)])  # two fixes ~220 m apart
    assert len(hm["cells"]) >= 15  # 12 m cells filled along the line


def test_empty():
    assert route_heatmap([])["cells"] == []
