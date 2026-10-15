from custom_components.bus_monitor.geo import (
    angle_diff_deg,
    bearing_deg,
    compass,
    distance_to_segment_m,
    haversine_m,
)


def test_haversine_one_degree_latitude():
    assert abs(haversine_m(40, -75, 41, -75) - 111_195) < 50


def test_bearing_cardinals():
    assert abs(bearing_deg(40, -75, 41, -75) - 0) < 0.01
    assert abs(bearing_deg(40, -75, 40, -74) - 90) < 0.5


def test_angle_diff_wraps():
    assert angle_diff_deg(350, 10) == 20
    assert angle_diff_deg(0, 180) == 180


def test_segment_distance_passes_beside_point():
    # point 0.001 deg east of the middle of a north-south segment (~85 m at lat 40)
    d = distance_to_segment_m(40.0005, -74.999, 40.0, -75.0, 40.001, -75.0)
    assert 80 < d < 90


def test_segment_distance_clamps_to_endpoint():
    d = distance_to_segment_m(40.002, -75.0, 40.0, -75.0, 40.001, -75.0)
    assert abs(d - haversine_m(40.002, -75.0, 40.001, -75.0)) < 1


def test_compass():
    assert compass(0) == "north"
    assert compass(359) == "north"
    assert compass(95) == "east"
