"""Data coordinator: polls Traccar, drives the alert engine and calibration."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .alerts import TripTracker
from .calibration import TrailRecorder, checkpoint_stats, typical_position
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_ALERT,
    EVENT_SHADOW,
    MIN_SCAN_INTERVAL,
    OPT_PROFILES,
    OPT_SCAN_INTERVAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .geocoder import OverpassGeocoder
from .models import Alert, BusConfig, Position, bus_label
from .traccar_client import CannotConnect, Device, InvalidAuth, TraccarClient

_LOGGER = logging.getLogger(__name__)

TRAIL_SAVE_INTERVAL_S = 60
# Use measured checkpoint timings for 'running late' once this many trips exist.
MIN_TRIPS_FOR_MEASURED_LEAD = 3
# Auto-placed checkpoints stay where the user put them until this many trips exist.
MIN_AUTO_TRIPS = 5


class BusMonitorCoordinator(DataUpdateCoordinator[dict[int, Position]]):
    """Holds the latest position per selected device."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TraccarClient,
        device_ids: list[int],
        devices: dict[int, Device],
    ) -> None:
        interval = max(
            MIN_SCAN_INTERVAL, int(entry.options.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.device_ids = device_ids
        self.devices = devices
        self.store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
        self.recorder = TrailRecorder()
        self.geocoder: OverpassGeocoder | None = None  # set during entry setup
        self.trackers: dict[str, TripTracker] = {}
        self.last_alert: dict[str, Alert] = {}
        self._saved_state: dict[str, dict | None] = {}
        self._base_configs: dict[str, BusConfig] = {}
        self.auto_positions: dict[str, dict[str, list]] = {}  # profile -> label -> [lat, lon, trips]
        self._last_save = 0.0
        for profile_id, raw in (entry.options.get(OPT_PROFILES) or {}).items():
            cfg = BusConfig.from_dict(profile_id, raw)
            if device := devices.get(cfg.device_id):
                cfg = replace(cfg, bus_name=bus_label(device.name))
            self.trackers[profile_id] = TripTracker(cfg)

    async def async_load(self) -> None:
        """Load recorded trips and today's trip state saved before a restart."""
        data = await self.store.async_load() or {}
        now = dt_util.now()
        self.recorder = TrailRecorder.from_dict(data, now)
        for profile_id, snap in (data.get("state") or {}).items():
            if tracker := self.trackers.get(profile_id):
                tracker.restore(snap, now.date())
        for tracker in self.trackers.values():
            self._apply_auto_positions(tracker)
            self._update_leads(tracker)
        self._saved_state = self._state()

    def _apply_auto_positions(self, tracker: TripTracker) -> None:
        """Move auto-placed checkpoints to where the bus typically is N minutes out.

        Works on the tracker's in-memory config only: the user's saved position stays
        in the options as the fallback, and nothing reloads.
        """
        pid = tracker.config.profile_id
        base = self._base_configs.get(pid, tracker.config)
        self._base_configs[pid] = base
        trips = self.recorder.trips_for(pid)
        placed: dict[str, list] = {}
        checkpoints = []
        for cp in base.checkpoints:
            pos = (
                typical_position(trips, cp.minutes, min_trips=MIN_AUTO_TRIPS)
                if cp.auto_place and cp.minutes and not cp.is_street
                else None
            )
            if pos:
                placed[cp.label] = [pos["lat"], pos["lon"], pos["trips"]]
                cp = replace(cp, lat=pos["lat"], lon=pos["lon"])
            checkpoints.append(cp)
        self.auto_positions[pid] = placed
        tracker.config = replace(base, checkpoints=tuple(checkpoints))

    def _update_leads(self, tracker: TripTracker) -> None:
        """Give the tracker measured checkpoint-to-stop minutes once there's enough data.

        Auto-placed checkpoints keep their nominal minutes: they're placed *at* that
        many minutes, and crossings recorded at their old spots would be stale.
        """
        trips = self.recorder.trips_for(tracker.config.profile_id)
        leads = {}
        for cp in tracker.config.checkpoints:
            if cp.auto_place or cp.is_street:
                continue
            stats = checkpoint_stats(trips, cp.label)
            if stats and stats["count"] >= MIN_TRIPS_FOR_MEASURED_LEAD:
                leads[cp.label] = stats["median"]
        tracker.lead_minutes = leads

    def _state(self) -> dict[str, dict | None]:
        return {pid: t.snapshot() for pid, t in self.trackers.items()}

    def data_to_save(self) -> dict:
        return {**self.recorder.as_dict(), "state": self._state()}

    def _maybe_save(self, force: bool = False) -> None:
        """Save when trip state changed, else at most once a minute (for the trail)."""
        now = time.monotonic()
        state = self._state()
        if force or state != self._saved_state or now - self._last_save > TRAIL_SAVE_INTERVAL_S:
            self._saved_state = state
            self._last_save = now
            self.store.async_delay_save(self.data_to_save, 1)

    @property
    def profiles_by_device(self) -> dict[int, list[TripTracker]]:
        out: dict[int, list[TripTracker]] = {}
        for tracker in self.trackers.values():
            out.setdefault(tracker.config.device_id, []).append(tracker)
        return out

    async def _async_update_data(self) -> dict[int, Position]:
        try:
            positions = await self.client.positions()
        except InvalidAuth as err:
            raise UpdateFailed("Traccar login was rejected") from err
        except CannotConnect as err:
            raise UpdateFailed(f"Cannot reach Traccar: {err}") from err

        data = {p.device_id: p for p in positions if p.device_id in self.device_ids}
        now = dt_util.now()
        save = False
        for tracker in self.trackers.values():
            cfg = tracker.config
            alerts: list[Alert] = []
            pos = data.get(cfg.device_id)
            if pos is not None:
                new = tracker.update(pos, now)
                alerts += new
                arrived_now = any(a.kind == "arrived" for a in new)
                if pos.valid and tracker.is_active(now) and (not tracker.arrived or arrived_now):
                    self.recorder.add_point(cfg.profile_id, pos)
            alerts += tracker.tick(now)
            for alert in alerts:
                self._publish(alert)
                if alert.kind == "arrived" and tracker.arrival_time is not None:
                    record = self.recorder.finish(
                        cfg.profile_id,
                        now.date().isoformat(),
                        tracker.arrival_time,
                        tracker.crossings,
                    )
                    save = save or record is not None
                    self._apply_auto_positions(tracker)
                    self._update_leads(tracker)
        self._maybe_save(force=save)
        return data

    def _publish(self, alert: Alert) -> None:
        if alert.kind == "checkpoint" and not alert.announce:
            self.hass.bus.async_fire(EVENT_SHADOW, alert.as_event_data())
            return
        self.last_alert[alert.profile_id] = alert
        _LOGGER.debug("Alert %s for %s", alert.kind, alert.bus_name)
        self.hass.bus.async_fire(EVENT_ALERT, alert.as_event_data())

    def reset_trip(self, profile_id: str) -> None:
        if tracker := self.trackers.get(profile_id):
            tracker.reset(dt_util.now().date())
            self.recorder.discard(profile_id)
            self._maybe_save(force=True)
            self.async_update_listeners()
