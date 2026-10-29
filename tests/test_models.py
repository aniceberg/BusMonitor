from custom_components.bus_monitor.models import Position, parse_traccar_time


def test_position_from_traccar_converts_knots():
    raw = {
        "deviceId": 7, "latitude": 40.1, "longitude": -75.2, "speed": 10.0, "course": 90,
        "fixTime": "2026-10-15T12:47:01.000+0000", "valid": True,
    }
    p = Position.from_traccar(raw)
    assert p.device_id == "7" and abs(p.speed_mps - 5.14444) < 1e-4
    assert p.fix_time.utcoffset().total_seconds() == 0


def test_parse_zulu():
    assert parse_traccar_time("2026-10-15T12:47:01Z").hour == 12
