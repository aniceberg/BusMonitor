"""No-bus days (holidays, snow days) and the summer pause after the school year ends."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bus_monitor.alerts import TripTracker
from custom_components.bus_monitor.calibration import TrailRecorder
from custom_components.bus_monitor.const import DOMAIN
from custom_components.bus_monitor.coordinator import IDLE_SCAN_INTERVAL
from custom_components.bus_monitor.models import Position, StopConfig, default_season_end
from custom_components.bus_monitor.profiles import entry_profiles

from .conftest import MONDAY_7AM, STOP_LAT, STOP_LON, make_config, pos
from .test_ha import DATA, PROFILE, _client, _edit, _line_trip

STOP = StopConfig(STOP_LAT, STOP_LON, 75, expected_arrival=time(7, 30), late_grace_min=5)


def _at(minute: float) -> datetime:
    return MONDAY_7AM + timedelta(minutes=minute)


def _parked(tracker: TripTracker, start: int, end: int, step: int = 1) -> list:
    """A tracker that keeps reporting while the bus sits in the depot (a little GPS drift)."""
    alerts = []
    for i, m in enumerate(range(start, end + 1, step)):
        t = _at(m)
        alerts += tracker.update(pos(39.95 + (i % 2) * 0.0003, at=t, speed_mps=0.3), t)
        alerts += tracker.tick(t)
    return alerts


# --- moved_today ----------------------------------------------------------------------

def test_parked_bus_with_drift_has_not_moved():
    tracker = TripTracker(make_config(stop=STOP))
    _parked(tracker, 0, 20)
    assert not tracker.moved_today
    assert tracker.wants_position(_at(20)) and not tracker.wants_fast_position(_at(20))


def test_speed_or_distance_counts_as_moving():
    fast = TripTracker(make_config(stop=STOP))
    fast.update(pos(39.95, at=_at(0), speed_mps=6), _at(0))
    assert fast.moved_today and fast.wants_fast_position(_at(0))

    rolled = TripTracker(make_config(stop=STOP))
    rolled.update(pos(39.95, at=_at(0)), _at(0))
    rolled.update(pos(39.953, at=_at(1)), _at(1))  # ~330 m, speed reported as 0
    assert rolled.moved_today


def test_yesterdays_fix_does_not_count_as_moving_today():
    tracker = TripTracker(make_config(stop=STOP))
    yesterday = _at(-24 * 60 + 600)  # Sunday 17:00, the last fix of a drive
    tracker.update(pos(39.95, at=yesterday, speed_mps=8), _at(0))
    assert not tracker.moved_today
    # the bus leaves the depot today: far from where it was parked overnight
    tracker.update(pos(39.955, at=_at(5)), _at(5))
    assert tracker.moved_today


def test_moved_survives_a_restart():
    tracker = TripTracker(make_config(stop=STOP))
    tracker.update(pos(39.95, at=_at(0), speed_mps=6), _at(0))
    fresh = TripTracker(make_config(stop=STOP))
    fresh.restore(tracker.snapshot(), MONDAY_7AM.date())
    assert fresh.moved_today


# --- a day the bus never comes ------------------------------------------------------

def test_no_bus_day_is_silent_and_stops_watching():
    tracker = TripTracker(make_config(stop=STOP, offline_after_min=10))
    alerts = _parked(tracker, 0, 50)  # past the late deadlines and 10 min with "no fix"
    assert alerts == []
    assert tracker.wants_position(_at(35))  # 07:35 = expected 07:30 + 5
    assert not tracker.wants_position(_at(36))
    assert tracker.display_status(_at(36)) == "not_running"


def test_silent_when_the_tracker_never_reports_at_all():
    tracker = TripTracker(make_config(stop=STOP, offline_after_min=10))
    assert [a for m in range(0, 60) for a in tracker.tick(_at(m))] == []


def test_a_late_bus_that_is_moving_is_still_announced_late():
    tracker = TripTracker(make_config(stop=STOP))
    tracker.update(pos(39.95, at=_at(0), speed_mps=5), _at(0))
    late = [a for m in range(0, 40) for a in tracker.tick(_at(m)) if a.kind == "late"]
    assert len(late) == 1
    assert tracker.wants_position(_at(40))  # not given up: it's coming


def test_without_an_arrival_time_it_watches_the_whole_window():
    tracker = TripTracker(make_config())
    _parked(tracker, 0, 50)
    assert tracker.wants_position(_at(120)) and tracker.display_status(_at(120)) == "idle"


def test_next_day_is_watched_again():
    tracker = TripTracker(make_config(stop=STOP))
    _parked(tracker, 0, 40)
    assert not tracker.wants_position(_at(40))
    tomorrow = _at(24 * 60)
    tracker.tick(tomorrow)
    assert tracker.wants_position(tomorrow) and not tracker.moved_today


# --- school year ------------------------------------------------------------------------

def test_default_season_end_is_the_coming_june_30():
    assert default_season_end(date(2026, 10, 31)) == date(2027, 6, 30)
    assert default_season_end(date(2027, 6, 30)) == date(2027, 6, 30)
    assert default_season_end(date(2027, 7, 1)) == date(2028, 6, 30)
    assert default_season_end(date(2027, 1, 15)) == date(2027, 6, 30)


def test_profile_pauses_after_the_school_year():
    tracker = TripTracker(make_config(season_end=date(2026, 10, 11)))  # the day before Monday
    assert not tracker.is_active(_at(0)) and not tracker.wants_position(_at(0))
    assert tracker.display_status(_at(0)) == "season_over"
    assert tracker.update(pos(39.95, at=_at(0), speed_mps=5), _at(0)) == []
    assert TripTracker(make_config(season_end=MONDAY_7AM.date())).is_active(_at(0))


def test_old_trips_age_out_when_loaded():
    now = datetime.now(UTC)
    rec = TrailRecorder(trips=[_line_trip(3), _line_trip(70)])
    loaded = TrailRecorder.from_dict(rec.as_dict(), now)
    assert [t.date for t in loaded.trips] == [_line_trip(3).date]


def test_forget_drops_only_that_profiles_trips():
    rec = TrailRecorder(trips=[_line_trip(1), _line_trip(2, "afternoon")])
    rec.add_point("morning", Position("1", 39.9, -75.0, datetime.now(UTC)))
    rec.forget("morning")
    assert [t.profile_id for t in rec.trips] == ["afternoon"] and rec.current_trail("morning") == []


# --- Home Assistant -------------------------------------------------------------------

async def _setup(hass, client, profiles, **kw):
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, minor_version=2, data=DATA, options={"profiles": profiles}, **kw
    )
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _tick(hass, seconds):
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_polls_slowly_until_the_bus_moves(hass: HomeAssistant):
    client = _client([Position("1", 39.95, -75.0, datetime.now(UTC))])
    entry = await _setup(hass, client, {"morning": PROFILE})
    coord = entry.runtime_data
    assert coord.update_interval == IDLE_SCAN_INTERVAL

    client.positions.return_value = [Position("1", 39.951, -75.0, datetime.now(UTC), speed_mps=6)]
    await _tick(hass, 61)
    assert coord.trackers["morning"].moved_today
    assert coord.update_interval == coord.fast_interval < IDLE_SCAN_INTERVAL


async def test_school_year_over_pauses_and_raises_a_repair(hass: HomeAssistant):
    client = _client([Position("1", 39.95, -75.0, datetime.now(UTC))])
    entry = await _setup(hass, client, {"morning": {**PROFILE, "season_end": "2020-06-30"}})
    issue_id = f"season_over_{entry.entry_id}_morning"
    assert hass.states.get("sensor.morning_status").state == "season_over"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    for _ in range(3):
        await _tick(hass, 30)
    assert client.positions.await_count == 1  # only the startup fetch

    # a past date is refused
    result = await _edit(hass, entry, client, "morning", {"season_end": "2021-06-30"})
    assert result["errors"] == {"season_end": "season_end_past"}

    # the next school year: watching again, the notice is gone
    end = default_season_end(datetime.now().date()).isoformat()
    result = await _edit(hass, entry, client, "morning", {"season_end": end})
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry_profiles(entry)["morning"]["season_end"] == end
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert hass.states.get("sensor.morning_status").state != "season_over"


async def test_profiles_get_a_school_year_end_on_upgrade(hass: HomeAssistant):
    client = _client([Position("1", 39.95, -75.0, datetime.now(UTC))])
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=DATA, options={"profiles": {"morning": PROFILE}})
    entry.add_to_hass(hass)
    with patch("custom_components.bus_monitor.TraccarClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.minor_version == 3
    expected = default_season_end(datetime.now().date()).isoformat()
    assert entry_profiles(entry)["morning"] == {**PROFILE, "season_end": expected}


async def test_relearn_forgets_the_profiles_trips(hass: HomeAssistant, hass_storage):
    hass_storage["bus_monitor.trips.relearn"] = {
        "version": 1,
        "key": "bus_monitor.trips.relearn",
        "data": {"trips": [t.as_dict() for t in (_line_trip(1), _line_trip(2), _line_trip(1, "afternoon"))]},
    }
    client = _client([Position("1", 39.95, -75.0, datetime.now(UTC))])
    profiles = {"morning": PROFILE, "afternoon": {**PROFILE, "name": "Afternoon"}}
    entry = await _setup(hass, client, profiles, entry_id="relearn")
    assert len(entry.runtime_data.recorder.trips_for("morning")) == 2

    await _edit(hass, entry, client, "morning", {"relearn": True})
    await hass.async_block_till_done()
    rec = entry.runtime_data.recorder
    assert rec.trips_for("morning") == [] and len(rec.trips_for("afternoon")) == 1
    assert "relearn" not in entry_profiles(entry)["morning"]
