"""Sidebar panel: static files, the bus icon set and panel (un)registration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, OPT_SHOW_PANEL, PANEL_URL_PATH, STATIC_URL

FRONTEND_DIR = Path(__file__).parent / "frontend"
WEBCOMPONENT = "bus-monitor-panel"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the panel files and register the icon set (once per HA run)."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("frontend_ready"):
        return
    version = (await async_get_integration(hass, DOMAIN)).version
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    # Loaded on every page so the sidebar can draw "busmonitor:bus".
    frontend.add_extra_js_url(hass, f"{STATIC_URL}/bus-monitor-icons.js?v={version}")
    data["frontend_ready"] = True
    data["version"] = version


async def async_update_panel(
    hass: HomeAssistant,
    *,
    setting_up: ConfigEntry | None = None,
    unloading: ConfigEntry | None = None,
) -> None:
    """Show the panel if any Bus Monitor entry wants it, otherwise remove it.

    `setting_up` isn't counted as loaded yet and `unloading` still is, so callers
    pass them explicitly.
    """
    data = hass.data.setdefault(DOMAIN, {})
    entries = [
        e
        for e in hass.config_entries.async_loaded_entries(DOMAIN)
        if unloading is None or e.entry_id != unloading.entry_id
    ]
    if setting_up is not None:
        entries.append(setting_up)
    wanted = any(e.options.get(OPT_SHOW_PANEL, True) for e in entries)
    registered = data.get("panel_registered", False)
    if wanted and not registered:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=WEBCOMPONENT,
            sidebar_title="Bus Monitor",
            sidebar_icon="busmonitor:bus",
            module_url=f"{STATIC_URL}/bus-monitor-panel.js?v={data.get('version', '0')}",
            require_admin=False,
        )
        data["panel_registered"] = True
    elif not wanted and registered:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
        data["panel_registered"] = False
