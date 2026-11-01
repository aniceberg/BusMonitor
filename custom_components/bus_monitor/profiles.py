"""Bus profiles, stored as config subentries of their provider entry."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import CONF_PROFILE_ID, DOMAIN, SUBENTRY_PROFILE


def profile_subentries(entry: ConfigEntry) -> dict[str, ConfigSubentry]:
    """{profile_id: subentry} for one provider entry."""
    return {
        sub.data[CONF_PROFILE_ID]: sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_PROFILE
    }


def profile_settings(subentry: ConfigSubentry) -> dict[str, Any]:
    """A profile's settings (what BusConfig.from_dict reads), without the id."""
    return {k: v for k, v in subentry.data.items() if k != CONF_PROFILE_ID}


def entry_profiles(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """{profile_id: settings} for one provider entry."""
    return {pid: profile_settings(sub) for pid, sub in profile_subentries(entry).items()}


def new_profile_subentry(profile_id: str, settings: dict[str, Any]) -> ConfigSubentry:
    return ConfigSubentry(
        data=MappingProxyType({**settings, CONF_PROFILE_ID: profile_id}),
        subentry_type=SUBENTRY_PROFILE,
        title=settings.get("name", profile_id),
        unique_id=profile_id,
    )


def taken_names(hass: HomeAssistant, except_id: str | None = None) -> set[str]:
    """Profile ids and name slugs in use in any Bus Monitor entry (services and the map
    find a profile by id across entries, so it must be unique everywhere)."""
    taken: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        for pid, settings in entry_profiles(entry).items():
            if pid != except_id:
                taken.update((pid, slugify(settings.get("name", pid))))
    return taken
