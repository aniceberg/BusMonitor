"""Every YAML sample in examples/ must paste cleanly and do what the docs say."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.components.automation.config import (
    async_validate_config_item as validate_automation,
)
from homeassistant.components.script.config import async_validate_config_item as validate_script
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

EXAMPLES = Path(__file__).parent.parent / "examples"
AUTOMATIONS = sorted((EXAMPLES / "automations").glob("*.yaml"))
SCRIPTS = sorted((EXAMPLES / "scripts").glob("*.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("path", [*AUTOMATIONS, *SCRIPTS], ids=lambda p: p.stem)
def test_guide_shows_each_tested_example_verbatim(path: Path):
    guide = (EXAMPLES.parent / "docs" / "automations.md").read_text()
    body = "\n".join(line for line in path.read_text().splitlines() if not line.startswith("#"))
    assert f"```yaml\n{body}\n```" in guide


def test_examples_exist():
    assert len(AUTOMATIONS) >= 5 and len(SCRIPTS) >= 2


@pytest.mark.parametrize("path", AUTOMATIONS, ids=lambda p: p.stem)
async def test_automation_example_is_valid(hass: HomeAssistant, path: Path):
    await async_setup_component(hass, "conversation", {})
    cfg = _load(path)
    assert isinstance(cfg, dict) and "automation" not in cfg  # the editor wants one automation
    result = await validate_automation(hass, path.stem, cfg)
    assert result.validation_error is None, result.validation_error


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.stem)
async def test_script_example_is_valid(hass: HomeAssistant, path: Path):
    cfg = _load(path)
    assert isinstance(cfg, dict) and "script" not in cfg
    result = await validate_script(hass, path.stem, cfg)
    assert result.validation_error is None, result.validation_error


async def _run_on_alert(hass: HomeAssistant, name: str, event_data: dict) -> list:
    speak = async_mock_service(hass, "tts", "speak")
    cfg = {"id": "t", **_load(EXAMPLES / "automations" / f"{name}.yaml")}
    assert await async_setup_component(hass, "automation", {"automation": [cfg]})
    await hass.async_block_till_done()
    hass.bus.async_fire("bus_monitor_alert", event_data)
    await hass.async_block_till_done()
    return speak


ALERT = {"kind": "checkpoint", "profile": "morning", "bus": "Bus 12", "message": "Bus 12 is about 10 minutes away."}


async def test_announce_all_speaks_the_message(hass: HomeAssistant):
    speak = await _run_on_alert(hass, "announce_all_alerts", ALERT)
    assert speak[0].data["message"] == ALERT["message"]


@pytest.mark.parametrize(
    ("data", "spoken"),
    [
        (ALERT, True),
        ({**ALERT, "kind": "arrived"}, True),
        ({**ALERT, "kind": "late"}, False),
        ({**ALERT, "profile": "afternoon"}, False),
    ],
)
async def test_announce_one_profile_filters(hass: HomeAssistant, data: dict, spoken: bool):
    speak = await _run_on_alert(hass, "announce_one_profile", data)
    assert bool(speak) is spoken


async def test_real_alert_events_carry_what_the_examples_use(hass: HomeAssistant):
    """The samples rely on these event fields, so a rename must fail here."""
    from custom_components.bus_monitor.alerts import TripTracker

    from .conftest import make_config, northbound_trail

    tracker = TripTracker(make_config(bus_name="Bus 12"))
    alerts = []
    for p in northbound_trail():
        alerts += tracker.update(p, p.fix_time)
    data = alerts[0].as_event_data()
    assert data["kind"] == "checkpoint" and data["profile"] == "am"
    assert data["message"] == "Bus 12 is about 10 minutes away."


async def test_assist_example_answers_with_the_location(hass: HomeAssistant):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    hass.services.async_register(
        "bus_monitor",
        "describe_location",
        lambda call: {"text": "Bus 12 is on Oak Avenue."},
        supports_response=SupportsResponse.ONLY,
    )
    cfg = {"id": "t", **_load(EXAMPLES / "automations" / "assist_where_is_the_bus.yaml")}
    assert await async_setup_component(hass, "automation", {"automation": [cfg]})
    await hass.async_block_till_done()
    result = await hass.services.async_call(
        "conversation", "process", {"text": "where's the bus"}, blocking=True, return_response=True
    )
    assert result["response"]["speech"]["plain"]["speech"] == "Bus 12 is on Oak Avenue."
