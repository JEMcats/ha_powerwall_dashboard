"""Constants for the Powerwall Dashboard integration."""

DOMAIN = "powerwall_dashboard"

CONF_PYPOWERWALL_URL = "pypowerwall_url"
CONF_INFLUXDB_URL = "influxdb_url"
CONF_TIMEZONE = "timezone"
CONF_ALLOW_CONTROLS = "allow_controls"
CONF_CONTROL_SECRET = "control_secret"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SHOW_STRINGS = "show_strings"

# pypowerwall proxy endpoints
PYPOWERWALL_AGGREGATES_PATH = "/api/meters/aggregates"
PYPOWERWALL_SOE_PATH = "/api/system_status/soe"
PYPOWERWALL_GRID_STATUS_PATH = "/api/system_status/grid_status"
PYPOWERWALL_STRINGS_PATH = "/strings"
PYPOWERWALL_TIME_REMAINING_PATH = "/pw/get_time_remaining"
PYPOWERWALL_UPDATE_STATUS_PATH = "/api/system/update/status"

# Read endpoints for the control entities (no token needed)
PYPOWERWALL_IS_CONNECTED_PATH = "/pw/is_connected"
PYPOWERWALL_GET_RESERVE_PATH = "/pw/get_reserve"
PYPOWERWALL_GET_MODE_PATH = "/pw/get_mode"

# /control endpoints: GET reads a setting, POST changes it (POST needs the secret)
CONTROL_RESERVE_PATH = "/control/reserve"
CONTROL_MODE_PATH = "/control/mode"
CONTROL_GRID_CHARGING_PATH = "/control/grid_charging"
CONTROL_GRID_EXPORT_PATH = "/control/grid_export"
CONTROL_MAX_BACKUP_PATH = "/control/max_backup"
CONTROL_ISLANDING_PATH = "/control/islanding"

# Used when /strings can't be read at startup, so the entities still get created.
DEFAULT_STRING_NAMES = ("A", "B", "C", "D", "E", "F")

# InfluxDB (v1) location of the Powerwall-Dashboard data
INFLUXDB_DATABASE = "powerwall"
INFLUXDB_RETENTION_POLICY = "autogen"
INFLUXDB_MEASUREMENT = "http"

# Polling interval in seconds, shared by both coordinators and user-configurable.
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 3600

# Firmware status rarely changes, so it is polled on its own, slower schedule.
SCAN_INTERVAL_UPDATE = 300

# Control settings are polled on their own schedule too, and the new value is
# shown immediately after a change is sent from Home Assistant.
SCAN_INTERVAL_CONTROL = 30

# Values the gateway uses for the two selects. The friendly labels
# ("Self-Powered", "Solar Only", ...) live in the translations.
OPERATING_MODES = ["self_consumption", "autonomous", "backup"]
GRID_EXPORT_MODES = ["battery_ok", "pv_only", "never"]

# Max backup: the server accepts 60 seconds and up. The duration entity works in
# minutes.
MAX_BACKUP_MIN_SECONDS = 60
MAX_BACKUP_MIN_MINUTES = 1
MAX_BACKUP_MAX_MINUTES = 10080  # 7 days
DEFAULT_MAX_BACKUP_MINUTES = 60

# Unique-ID suffixes of every entity that only exists when controls are enabled.
CONTROL_ENTITY_KEYS = (
    "grid_connection",
    "backup_reserve",
    "operating_mode",
    "grid_charging",
    "grid_export",
    "max_backup",
    "max_backup_duration",
    "max_backup_ends",
    "storm_watch_active",
)

# Sensor key -> InfluxDB field whose daily integral (in kWh) feeds that sensor
ENERGY_FIELDS: dict[str, str] = {
    "battery_charged": "to_pw",
    "battery_discharged": "from_pw",
    "grid_exported": "to_grid",
    "grid_imported": "from_grid",
    "home_usage": "home",
    "solar_generated": "solar",
}
