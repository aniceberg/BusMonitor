"""Home Assistant level tests for the Bouncie provider and the v1 -> v2 entry migration."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bus_monitor.const import DOMAIN, EVENT_ALERT
from custom_components.bus_monitor.models import Position
from custom_components.bus_monitor.providers import Device, InvalidAuth
from custom_components.bus_monitor.providers.bouncie import AUTHORIZE_URL, TOKEN_URL

from .test_ha import CONN, DATA, PROFILE, _client

IMEI = "353000000000001"
REDIRECT = "https://example.com/auth/external/callback"
USER = {"id": "65f8a2b4c9d7e1234567890d", "email": "parent@example.com", "name": "Pat"}


@pytest.fixture
async def credentials(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential("cid", "secret"))


def _bouncie(positions=None):
    client = AsyncMock()
    client.name = client.manufacturer = "Bouncie"
    client.user = AsyncMock(return_value=USER)
    client.devices = AsyncMock(return_value=[Device(IMEI, "Carpool van", "VIN1")])
    client.positions = AsyncMock(return_value=positions or [])
    return client


def _entry(**data):
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=f"bouncie|{USER['id']}",
        data={
            "provider": "bouncie",
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "a",
                "refresh_token": "r",
                "expires_in": 3600,
                "expires_at": time.time() + 3600,
            },
            "devices": [IMEI],
            **data,
        },
        options={"profiles": {"carpool": {**PROFILE, "device_id": IMEI, "name": "Carpool"}}},
    )


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_bouncie_oauth_flow(hass: HomeAssistant, hass_client_no_auth, aioclient_mock):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bouncie"}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith(f"{AUTHORIZE_URL}?response_type=code&client_id=cid")

    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    resp = await (await hass_client_no_auth()).get(f"/auth/external/callback?code=abc&state={state}")
    assert resp.status == 200
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "a", "refresh_token": "r", "expires_in": 3600, "token_type": "Bearer"},
    )
    with patch("custom_components.bus_monitor.config_flow.BouncieClient", return_value=_bouncie()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["step_id"] == "devices"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"devices": [IMEI]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bouncie (Pat)"
    assert result["result"].unique_id == f"bouncie|{USER['id']}"
    data = result["data"]
    assert (data["provider"], data["devices"], data["token"]["access_token"]) == ("bouncie", [IMEI], "a")


@pytest.mark.usefixtures("credentials")
async def test_bouncie_entry_tracks_and_alerts(hass: HomeAssistant):
    now = datetime.now(UTC)
    client = _bouncie([Position(IMEI, 39.980, -75.0, now - timedelta(seconds=30), speed_mps=5, course=0.0)])
    entry = _entry()
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.BouncieClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("device_tracker.carpool_van") is not None
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, IMEI), entry.entry_id)
    assert device.manufacturer == "Bouncie" and device.name == "Carpool van"

    events = []
    hass.bus.async_listen(EVENT_ALERT, events.append)
    client.positions.return_value = [Position(IMEI, 39.9905, -75.0, now, speed_mps=5, course=0.0)]
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=60))
    await hass.async_block_till_done()
    assert [(e.data["label"], e.data["bus"]) for e in events] == [("5 min", "Bus Carpool van")]


@pytest.mark.usefixtures("credentials")
async def test_traccar_and_bouncie_entries_side_by_side(hass: HomeAssistant):
    """Same raw id in both providers must still give two separate devices."""
    now = datetime.now(UTC)
    traccar = MockConfigEntry(
        domain=DOMAIN, version=2, data=DATA, options={"profiles": {"morning": PROFILE}}
    )
    bouncie = _entry(devices=["1"])
    bouncie.add_to_hass(hass)
    traccar.add_to_hass(hass)
    bouncie_client = _bouncie([Position("1", 39.98, -75.0, now)])
    bouncie_client.devices.return_value = [Device("1", "Carpool van", "VIN1")]
    with (
        patch("custom_components.bus_monitor.TraccarClient", return_value=_client([Position("1", 39.98, -75.0, now)])),
        patch("custom_components.bus_monitor.BouncieClient", return_value=bouncie_client),
    ):
        hass.config_entries.async_update_entry(
            bouncie, options={"profiles": {"carpool": {**PROFILE, "name": "Carpool"}}}
        )
        assert await async_setup_component(hass, DOMAIN, {})  # loads both entries
        await hass.async_block_till_done()

    reg = dr.async_get(hass)
    ident = (DOMAIN, "1")
    assert reg.async_get_device_by_identifier(ident, traccar.entry_id).manufacturer == "Traccar"
    assert reg.async_get_device_by_identifier(ident, bouncie.entry_id).manufacturer == "Bouncie"
    assert hass.states.get("device_tracker.bus_12") and hass.states.get("device_tracker.carpool_van")
    assert hass.states.get("sensor.bus_12_morning_status").state == "en_route"
    assert hass.states.get("sensor.carpool_van_carpool_status").state == "en_route"


async def test_v1_traccar_entry_migrates_and_keeps_entities(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={**CONN, "devices": [1]},
        options={"profiles": {"morning": {**PROFILE, "device_id": 1}}, "scan_interval": 20},
    )
    entry.add_to_hass(hass)
    # entity registered by v0.2 under the same unique_id
    er.async_get(hass).async_get_or_create(
        "device_tracker", DOMAIN, f"{entry.entry_id}_1_tracker", suggested_object_id="bus_12"
    )
    with patch(
        "custom_components.bus_monitor.TraccarClient",
        return_value=_client([Position("1", 39.98, -75.0, datetime.now(UTC))]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.data == DATA
    assert entry.options["profiles"]["morning"]["device_id"] == "1"
    assert entry.options["scan_interval"] == 20
    assert hass.states.get("device_tracker.bus_12") is not None
    assert hass.states.get("device_tracker.bus_12_2") is None


@pytest.mark.usefixtures("credentials")
async def test_rejected_login_while_running_starts_reauth(hass: HomeAssistant):
    client = _bouncie([Position(IMEI, 39.98, -75.0, datetime.now(UTC))])
    entry = _entry()
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.BouncieClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    client.positions.side_effect = InvalidAuth
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=60))
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [("reauth", "reauth_bouncie")]
