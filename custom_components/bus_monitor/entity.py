"""Shared entity bases."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alerts import TripTracker
from .const import DOMAIN
from .coordinator import BusMonitorCoordinator


def bus_device_info(coordinator: BusMonitorCoordinator, device_id: str) -> DeviceInfo:
    """The device for one bus. Identifiers are scoped per config entry, so the same id
    from two providers is fine."""
    device = coordinator.devices.get(device_id)
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=device.name if device else f"Bus {device_id}",
        manufacturer=coordinator.client.manufacturer,
    )


class BusEntity(CoordinatorEntity[BusMonitorCoordinator]):
    """An entity attached to one physical bus (a vehicle in the tracking provider)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusMonitorCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_device_info = bus_device_info(coordinator, device_id)


class ProfileEntity(BusEntity):
    """An entity for one bus profile (bus + stop + time window).

    Each profile is a config subentry and gets its own device (a device belongs to one
    subentry), linked to the bus it follows. Entity unique_ids don't depend on the device,
    so entity IDs from before profiles were subentries are kept.
    """

    def __init__(self, coordinator: BusMonitorCoordinator, tracker: TripTracker, key: str) -> None:
        super().__init__(coordinator, tracker.config.device_id)
        self._tracker = tracker
        cfg = tracker.config
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{cfg.profile_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"profile_{cfg.profile_id}")},
            name=cfg.name,
            model="Bus profile",
            manufacturer="Bus Monitor",
        )
        if bus := coordinator.bus_devices.get(cfg.device_id):
            self._attr_device_info["via_device_id"] = bus
