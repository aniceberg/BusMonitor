from datetime import timedelta

import pytest

from custom_components.bus_monitor.calibration import TripRecord
from custom_components.bus_monitor.describe import compose, estimate_eta_min, speakable
from custom_components.bus_monitor.models import Checkpoint
from custom_components.bus_monitor.streets import describe_position, parse_overpass

from .conftest import MONDAY_7AM


def _way(wid, name, nodes_latlon):
    return {
        "type": "way",
        "id": wid,
        "tags": {"highway": "residential", "name": name},
        "nodes": [n for n, _, _ in nodes_latlon],
        "geometry": [{"lat": la, "lon": lo} for _, la, lo in nodes_latlon],
    }


# Oak Ave runs north-south at lon -75.0, split into two OSM ways at the 3rd St junction.
OVERPASS = {
    "elements": [
        _way(1, "Oak Ave", [(10, 39.998, -75.0), (11, 40.000, -75.0)]),
        _way(2, "Oak Ave", [(11, 40.000, -75.0), (12, 40.003, -75.0), (13, 40.005, -75.0)]),
        _way(3, "3rd St", [(20, 40.000, -75.002), (11, 40.000, -75.0), (21, 40.000, -74.998)]),
        _way(4, "5th St", [(30, 40.003, -75.002), (12, 40.003, -75.0), (31, 40.003, -74.998)]),
        {"type": "way", "id": 5, "tags": {"highway": "service"}, "nodes": [1], "geometry": [{"lat": 1, "lon": 1}]},
    ]
}


@pytest.fixture
def ways():
    return parse_overpass(OVERPASS)


def test_parse_skips_unnamed(ways):
    assert {w.name for w in ways} == {"Oak Ave", "3rd St", "5th St"}


def test_heading_north_between_cross_streets(ways):
    info = describe_position(40.0015, -75.0, 0.0, ways)
    assert (info.street, info.behind, info.ahead) == ("Oak Ave", "3rd St", "5th St")
    assert info.directional


def test_heading_south_swaps_sides(ways):
    info = describe_position(40.0015, -75.0, 180.0, ways)
    assert (info.behind, info.ahead) == ("5th St", "3rd St")


def test_unknown_heading_is_not_directional(ways):
    info = describe_position(40.0015, -75.0, None, ways)
    assert info.street == "Oak Ave" and not info.directional
    assert {info.behind, info.ahead} == {"3rd St", "5th St"}


def test_only_one_side_known(ways):
    info = describe_position(40.0045, -75.0, 0.0, ways)  # past 5th St, nothing ahead in data
    assert (info.behind, info.ahead) == ("5th St", None)


def test_no_ways():
    assert describe_position(40.0, -75.0, 0.0, []).street is None


def test_speakable_expands_abbreviations():
    assert speakable("N Oak Ave") == "North Oak Avenue"
    assert speakable("Main St.") == "Main Street"
    assert speakable("St") == "St"  # a one-word name is left alone


def test_compose_full_sentence(ways):
    info = describe_position(40.0015, -75.0, 0.0, ways)
    text = compose(bus_name="Bus 12", info=info, heading=0.0, speed_mps=8, age_s=20,
                   distance_to_stop_m=1287, eta_min=6, arrived=False)
    assert text == ("Bus 12 is on Oak Avenue between 3rd Street and 5th Street, heading north, "
                    "about 0.8 miles from your stop, roughly 6 minutes away.")


def test_compose_far_from_road_stopped_stale_and_arrived(ways):
    info = describe_position(40.0015, -74.998, 0.0, ways)  # ~170 m east of Oak Ave
    text = compose(bus_name="Bus 12", info=info, heading=None, speed_mps=0, age_s=1300,
                   distance_to_stop_m=50, eta_min=1, arrived=False)
    assert text.startswith("Bus 12 last reported 22 minutes ago. Bus 12 was near")
    assert "currently stopped" in text and "160 feet" in text and "1 minute away" in text
    assert compose(bus_name="Bus 12", info=None, heading=None, speed_mps=0, age_s=0,
                   distance_to_stop_m=None, eta_min=None, arrived=True) == "Bus 12 has arrived at your stop."


def test_compose_without_street_lookup():
    text = compose(bus_name="Bus 12", info=None, heading=90.0, speed_mps=5, age_s=5,
                   distance_to_stop_m=None, eta_min=None, arrived=False)
    assert "couldn't name a street" in text and "heading east" in text


def test_eta_uses_baseline_then_nominal():
    cps = (Checkpoint("10 min", 0, 0, minutes=10), Checkpoint("5 min", 0, 0, minutes=5))
    crossed = {"5 min": MONDAY_7AM}
    now = MONDAY_7AM + timedelta(minutes=2)
    assert estimate_eta_min({}, cps, [], now) is None
    assert estimate_eta_min(crossed, cps, [], now) == 3  # nominal 5 - 2 elapsed
    trip = TripRecord("am", "2026-10-12", MONDAY_7AM + timedelta(minutes=7), crossed, [])
    assert estimate_eta_min(crossed, cps, [trip], now) == 5  # measured 7 - 2 elapsed
    assert estimate_eta_min(crossed, cps, [], MONDAY_7AM + timedelta(minutes=30)) == 1  # clamped
