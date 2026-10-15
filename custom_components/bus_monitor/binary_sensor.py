"""Running-late binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BusMonitorConfigEntry
from .entity import ProfileEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BusMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(LateSensor(coordinator, t) for t in coordinator.trackers.values())


class LateSensor(ProfileEntity, BinarySensorEntity):
    def __init__(self, coordinator, tracker) -> None:
        super().__init__(coordinator, tracker, "late")
        self._attr_name = f"{tracker.config.name} running late"

    @property
    def is_on(self) -> bool:
        return self._tracker.late_fired and not self._tracker.arrived
