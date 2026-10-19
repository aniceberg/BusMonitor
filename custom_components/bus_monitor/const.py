"""Constants for Bus Monitor."""

DOMAIN = "bus_monitor"

CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_DEVICES = "devices"  # data: list of selected Traccar device ids

# options
OPT_PROFILES = "profiles"  # {profile_id: {device_id, name, stop, checkpoints, ...}}
OPT_SCAN_INTERVAL = "scan_interval"
OPT_SHOW_PANEL = "show_panel"  # Bus Monitor map in the sidebar (default on)

DEFAULT_SCAN_INTERVAL = 10  # seconds
MIN_SCAN_INTERVAL = 5

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
