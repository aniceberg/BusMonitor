"""Status, distance, last-alert and baseline sensors."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BusMonitorConfigEntry
from .alerts import STATUS_ARRIVED, STATUS_EN_ROUTE, STATUS_IDLE, STATUS_NEAR
from .calibration import checkpoint_stats
from .entity import ProfileEntity
from .geo import haversine_m


async def async_setup_entry(
    hass: HomeAssistant, entry: BusMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[ProfileEntity] = []
    for tracker in coordinator.trackers.values():
        entities.append(StatusSensor(coordinator, tracker))
        entities.append(LastAlertSensor(coordinator, tracker))
        if tracker.config.stop:
            entities.append(DistanceSensor(coordinator, tracker))
        entities.extend(
            BaselineSensor(coordinator, tracker, c.label) for c in tracker.config.checkpoints
        )
    async_add_entities(entities)


class StatusSensor(ProfileEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_IDLE, STATUS_EN_ROUTE, STATUS_NEAR, STATUS_ARRIVED]

    def __init__(self, coordinator, tracker) -> None:
        super().__init__(coordinator, tracker, "status")
        self._attr_name = f"{tracker.config.name} status"

    @property
    def native_value(self) -> str:
        return self._tracker.status


class LastAlertSensor(ProfileEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, tracker) -> None:
        super().__init__(coordinator, tracker, "last_alert")
        self._attr_name = f"{tracker.config.name} last alert"

    @property
    def native_value(self) -> datetime | None:
        alert = self.coordinator.last_alert.get(self._tracker.config.profile_id)
        return alert.time if alert else None

    @property
    def extra_state_attributes(self) -> dict:
        alert = self.coordinator.last_alert.get(self._tracker.config.profile_id)
        return alert.as_event_data() if alert else {}


class DistanceSensor(ProfileEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_unit_of_measurement = UnitOfLength.MILES
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, tracker) -> None:
        super().__init__(coordinator, tracker, "distance")
        self._attr_name = f"{tracker.config.name} distance to stop"

    @property
    def native_value(self) -> float | None:
        pos = (self.coordinator.data or {}).get(self._tracker.config.device_id)
        stop = self._tracker.config.stop
        if not pos or not stop:
            return None
        return round(haversine_m(pos.lat, pos.lon, stop.lat, stop.lon))


class BaselineSensor(ProfileEntity, SensorEntity):
    """Median actual minutes from this checkpoint to the stop (the baseline)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, tracker, label: str) -> None:
        super().__init__(coordinator, tracker, f"baseline_{label}")
        self._label = label
        self._attr_name = f"{tracker.config.name} {label} actual minutes"

    def _stats(self) -> dict | None:
        trips = self.coordinator.recorder.trips_for(self._tracker.config.profile_id)
        return checkpoint_stats(trips, self._label)

    @property
    def native_value(self) -> float | None:
        stats = self._stats()
        return stats["median"] if stats else None

    @property
    def extra_state_attributes(self) -> dict:
        return self._stats() or {}
