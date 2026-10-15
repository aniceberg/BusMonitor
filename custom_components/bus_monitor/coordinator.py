"""Data coordinator: polls Traccar, drives the alert engine and calibration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .alerts import TripTracker
from .calibration import TrailRecorder
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
from .models import Alert, BusConfig, Position
from .traccar_client import CannotConnect, Device, InvalidAuth, TraccarClient

_LOGGER = logging.getLogger(__name__)


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
        for profile_id, raw in (entry.options.get(OPT_PROFILES) or {}).items():
            cfg = BusConfig.from_dict(profile_id, raw)
            self.trackers[profile_id] = TripTracker(cfg)

    async def async_load(self) -> None:
        self.recorder = TrailRecorder.from_dict(await self.store.async_load())

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
        if save:
            self.store.async_delay_save(self.recorder.as_dict, 30)
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
            self.async_update_listeners()
