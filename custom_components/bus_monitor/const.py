"""Constants for Bus Monitor."""

DOMAIN = "bus_monitor"

CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICES = "devices"  # data: list of selected vehicle ids (str)
CONF_PROVIDER = "provider"  # data: which tracking provider this entry reads from

PROVIDER_TRACCAR = "traccar"
PROVIDER_BOUNCIE = "bouncie"

# options
OPT_PROFILES = "profiles"  # {profile_id: {device_id, name, stop, checkpoints, ...}}
OPT_SCAN_INTERVAL = "scan_interval"
OPT_SHOW_PANEL = "show_panel"  # Bus Monitor map in the sidebar (default on)

# Polling seconds per provider as (default, minimum). Bouncie's cloud API is polled more
# gently until we know how often it refreshes (scripts/bouncie_probe.py).
SCAN_INTERVALS = {PROVIDER_TRACCAR: (10, 5), PROVIDER_BOUNCIE: (30, 15)}

EVENT_ALERT = "bus_monitor_alert"
EVENT_SHADOW = "bus_monitor_shadow"  # shadow-mode checkpoint crossings (never announced)

STORAGE_KEY = f"{DOMAIN}.trips"
STORAGE_VERSION = 1
STREETS_STORAGE_KEY = f"{DOMAIN}.streets"
STREETS_STORAGE_VERSION = 1

SERVICE_RESET_TRIP = "reset_trip"
SERVICE_SUGGEST = "suggest_checkpoints"
SERVICE_DESCRIBE = "describe_location"

PANEL_URL_PATH = "bus-monitor"
STATIC_URL = "/bus_monitor_static"
