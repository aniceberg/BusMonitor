"""Shared entity bases."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alerts import TripTracker
from .const import DOMAIN
from .coordinator import BusMonitorCoordinator


class BusEntity(CoordinatorEntity[BusMonitorCoordinator]):
    """An entity attached to one physical bus (a vehicle in the tracking provider)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusMonitorCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.devices.get(device_id)
        # Identifiers are scoped per config entry, so the same id from two providers is fine.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device.name if device else f"Bus {device_id}",
            manufacturer=coordinator.client.manufacturer,
        )


class ProfileEntity(BusEntity):
    """An entity for one bus profile (bus + stop + time window)."""

    def __init__(self, coordinator: BusMonitorCoordinator, tracker: TripTracker, key: str) -> None:
        super().__init__(coordinator, tracker.config.device_id)
        self._tracker = tracker
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{tracker.config.profile_id}_{key}"
