"""The announcement blueprint must import and do what it says."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.bus_monitor.const import EVENT_ALERT

BLUEPRINT = "bus_monitor/announce_bus_alerts.yaml"
SOURCE = Path(__file__).parent.parent / "blueprints" / "automation" / BLUEPRINT


async def _automation(hass: HomeAssistant, tmp_path: Path, **inputs) -> list:
    """Install the blueprint in a temporary config dir and create one automation from it."""
    target = tmp_path / "blueprints" / "automation" / BLUEPRINT
    target.parent.mkdir(parents=True)
    shutil.copy(SOURCE, target)
    hass.config.config_dir = str(tmp_path)
    calls = async_mock_service(hass, "tts", "speak")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": BLUEPRINT,
                    "input": {
                        "tts_entity": "tts.voice",
                        "speakers": ["media_player.kitchen"],
                        **inputs,
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


async def _fire(hass: HomeAssistant, kind: str = "checkpoint", profile: str = "morning") -> None:
    hass.bus.async_fire(
        EVENT_ALERT,
        {"kind": kind, "profile": profile, "message": "Bus 12 is about 10 minutes away."},
    )
    await hass.async_block_till_done()


async def test_speaks_every_alert_by_default(hass: HomeAssistant, tmp_path: Path):
    calls = await _automation(hass, tmp_path)
    for kind in ("checkpoint", "arrived", "late", "offline"):
        await _fire(hass, kind)
    assert len(calls) == 4
    assert calls[0].data["entity_id"] in ("tts.voice", ["tts.voice"])
    assert calls[0].data["media_player_entity_id"] == ["media_player.kitchen"]
    assert calls[0].data["message"] == "Bus 12 is about 10 minutes away."


@pytest.mark.parametrize(
    ("inputs", "kind", "profile", "spoken"),
    [
        ({"alert_kinds": ["arrived"]}, "arrived", "morning", True),
        ({"alert_kinds": ["arrived"]}, "late", "morning", False),
        ({"profiles": ["morning"]}, "late", "morning", True),
        ({"profiles": ["morning"]}, "late", "afternoon", False),
    ],
)
async def test_filters(hass: HomeAssistant, tmp_path: Path, inputs, kind, profile, spoken):
    calls = await _automation(hass, tmp_path, **inputs)
    await _fire(hass, kind, profile)
    assert bool(calls) is spoken
