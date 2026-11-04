"""The diagnostics download must be safe to attach to a public issue."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bus_monitor.const import DOMAIN
from custom_components.bus_monitor.diagnostics import async_get_config_entry_diagnostics
from custom_components.bus_monitor.models import Position

from .test_ha import _client

SECRET_DATA = {
    "provider": "traccar",
    "base_url": "http://secret-host.example:8082",
    "username": "secret-user@example.com",
    "password": "secret-password",
    "devices": ["9001"],
}
PROFILE = {
    "device_id": "9001",
    "name": "Secret profile name",
    "announce_as": "Secret spoken name",
    "stop": {"lat": 11.23456, "lon": -22.65432, "radius_m": 75, "expected_arrival": "07:40", "late_grace_min": 5},
    "checkpoints": [
        {"label": "Secret Street", "kind": "street", "minutes": 0, "lat": 11.11111, "lon": -22.22222, "radius_m": 60, "announce": True},
        {"label": "10 min", "kind": "time", "minutes": 10, "auto_place": True, "lat": 11.33333, "lon": -22.44444, "radius_m": 100, "announce": False},
    ],
    "active_start": "00:00",
    "active_end": "23:59",
    "weekdays": [0, 1, 2, 3, 4, 5, 6],
}
FORBIDDEN = [
    "secret",
    "9001",
    "morning_run",
    "11.2",
    "22.6",
    "11.1",
    "22.2",
    "11.3",
    "22.4",
    "11.5",
    "22.7",
]


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="secret title",
        unique_id="secret-host|secret-user",
        data=SECRET_DATA,
        options={"profiles": {"morning_run": PROFILE}},
    )


def _assert_clean(diag: dict) -> None:
    dumped = json.dumps(diag).lower()
    for forbidden in FORBIDDEN:
        assert forbidden not in dumped, forbidden


async def test_diagnostics_of_a_running_entry(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _client([Position("9001", 11.55555, -22.77777, now - timedelta(seconds=30), speed_mps=5, course=0.0)])
    from custom_components.bus_monitor.providers import Device

    client.devices.return_value = [Device("9001", "Secret bus name", "secret-unique-id")]
    entry = _entry()
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    _assert_clean(diag)
    assert diag["entry"]["provider"] == "traccar"
    assert diag["entry"]["server_scheme"] == "http"
    assert diag["entry"]["state"] == "loaded"
    assert diag["polling"]["last_update_success"] is True
    assert diag["vehicles"][0]["ref"] == "vehicle_1"
    assert 25 <= diag["vehicles"][0]["fix"]["age_seconds"] <= 60
    profile = diag["profiles"][0]
    assert profile["ref"] == "profile_1"
    assert profile["vehicle"] == "vehicle_1"
    assert profile["announce_as_set"] is True
    assert profile["stop"]["expected_arrival"] == "07:40"
    assert profile["checkpoints"] == {"total": 2, "street": 1, "auto_placed": 1, "shadow": 1}
    assert profile["trips_recorded"] == 0


async def test_diagnostics_when_setup_failed(hass: HomeAssistant):
    from custom_components.bus_monitor.providers import CannotConnect

    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.bus_monitor.TraccarClient",
        return_value=_client(login_exc=CannotConnect("http://secret-host.example:8082 is down")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    _assert_clean(diag)
    assert diag["entry"]["state"] == "setup_retry"
    assert diag["polling"] is None
    assert diag["vehicles"][0]["seen_on_account"] is None
    assert diag["profiles"][0]["status"] is None
