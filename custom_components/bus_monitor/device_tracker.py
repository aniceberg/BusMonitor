"""Live bus location."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BusMonitorConfigEntry
from .entity import BusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BusMonitorConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(BusTracker(coordinator, i) for i in coordinator.device_ids)


class BusTracker(BusEntity, TrackerEntity):
    _attr_name = None
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{device_id}_tracker"

    @property
    def available(self) -> bool:
        return super().available and self._device_id in (self.coordinator.data or {})

    @property
    def latitude(self) -> float | None:
        pos = (self.coordinator.data or {}).get(self._device_id)
        return pos.lat if pos else None

    @property
    def longitude(self) -> float | None:
        pos = (self.coordinator.data or {}).get(self._device_id)
        return pos.lon if pos else None

    @property
    def extra_state_attributes(self) -> dict:
        pos = (self.coordinator.data or {}).get(self._device_id)
        if not pos:
            return {}
        return {
            "speed_mph": round(pos.speed_mps * 2.23694, 1),
            "course": pos.course,
            "last_fix": pos.fix_time.isoformat(),
        }
