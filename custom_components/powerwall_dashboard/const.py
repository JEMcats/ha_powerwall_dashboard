"""Constants for the Powerwall Dashboard integration."""

DOMAIN = "powerwall_dashboard"

CONF_PYPOWERWALL_URL = "pypowerwall_url"
CONF_INFLUXDB_URL = "influxdb_url"
CONF_TIMEZONE = "timezone"
CONF_ALLOW_CONTROLS = "allow_controls"
CONF_CONTROL_SECRET = "control_secret"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SHOW_STRINGS = "show_strings"
CONF_TEMPERATURE_UNIT = "temperature_unit"

# pypowerwall proxy endpoints
PYPOWERWALL_AGGREGATES_PATH = "/api/meters/aggregates"
PYPOWERWALL_SOE_PATH = "/api/system_status/soe"
PYPOWERWALL_GRID_STATUS_PATH = "/api/system_status/grid_status"
PYPOWERWALL_STRINGS_PATH = "/strings"
PYPOWERWALL_TIME_REMAINING_PATH = "/pw/get_time_remaining"
PYPOWERWALL_UPDATE_STATUS_PATH = "/api/system/update/status"

# Per-Powerwall diagnostics. /pod lists the Powerwalls (PW1, PW2, ...) with their
# capacity and charge; /temps/pw and /fans/pw are the simplified forms of /temps
# and /fans, numbered the same way (PW1 is the leader).
PYPOWERWALL_POD_PATH = "/pod"
PYPOWERWALL_TEMPS_PATH = "/temps/pw"
PYPOWERWALL_FANS_PATH = "/fans/pw"

# Read endpoints for the control entities (no token needed). The grid connection
# switch reads PYPOWERWALL_GRID_STATUS_PATH, the same data as the Grid status sensor.
PYPOWERWALL_GET_RESERVE_PATH = "/pw/get_reserve"
PYPOWERWALL_GET_MODE_PATH = "/pw/get_mode"

# /control endpoints: GET reads a setting, POST changes it (POST needs the secret)
CONTROL_RESERVE_PATH = "/control/reserve"
CONTROL_MODE_PATH = "/control/mode"
CONTROL_GRID_CHARGING_PATH = "/control/grid_charging"
CONTROL_GRID_EXPORT_PATH = "/control/grid_export"
CONTROL_MAX_BACKUP_PATH = "/control/max_backup"
CONTROL_ISLANDING_PATH = "/control/islanding"

# How the gateway reports the grid -> the state shown by the Grid status sensor.
# The Grid connection switch uses the same map: "connected" is on, "disconnected"
# (islanded) is off, and "transitioning" is unknown.
GRID_STATUS_MAP = {
    "SystemGridConnected": "connected",
    "SystemIslandedActive": "disconnected",
    "SystemTransitionToGrid": "transitioning",
}

# Used when /strings can't be read at startup, so the entities still get created.
DEFAULT_STRING_NAMES = ("A", "B", "C", "D", "E", "F")

# InfluxDB (v1) location of the Powerwall-Dashboard data
INFLUXDB_DATABASE = "powerwall"
INFLUXDB_RETENTION_POLICY = "autogen"
INFLUXDB_MEASUREMENT = "http"

# Polling interval in seconds, shared by every coordinator (live data, InfluxDB,
# firmware status, diagnostics and controls) and user-configurable.
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 3600

# Temperature display unit choices (option key -> Home Assistant unit). The
# gateway reports Celsius; the sensors convert to the chosen unit.
TEMPERATURE_UNITS = {"celsius": "°C", "fahrenheit": "°F", "kelvin": "K"}
DEFAULT_TEMPERATURE_UNIT = "celsius"

# Powerwall 3 has two fans per unit. /fans/pw numbers them FAN1, FAN2, ... in
# the same order as the Powerwalls, so PW1 owns FAN1-2, PW2 owns FAN3-4, etc.
FANS_PER_POWERWALL = 2

# Published capacity (kWh) by part number prefix, taken from the Tesla datasheets.
# The prefix is the first block of the part number in a /pod name, e.g. the
# "1707000" in "TEPOD--1707000-30-L--TG126034...". Unknown parts use the default.
# The capacity deviation sensors compare the gateway's "nominal full pack energy"
# with this figure.
DEFAULT_POWERWALL_SPEC_KWH = 13.5
POWERWALL_MODELS: dict[str, tuple[str, float]] = {
    "1092170": ("Powerwall 2", 13.5),
    "2012170": ("Powerwall 2", 13.5),
    "3012170": ("Powerwall 2", 13.5),
    "1707000": ("Powerwall 3", 13.5),
    "1807000": ("Powerwall 3 Expansion", 13.5),
}

# Values the gateway uses for the two selects. The friendly labels
# ("Self-Powered", "Solar Only", ...) live in the translations.
OPERATING_MODES = ["self_consumption", "autonomous", "backup"]
GRID_EXPORT_MODES = ["battery_ok", "pv_only", "never"]

# Max backup: the server accepts 60 seconds up to this many seconds.
MAX_BACKUP_MIN_SECONDS = 60
MAX_BACKUP_MAX_SECONDS = 4294967295

# The server caches /control/max_backup for 30 seconds. After a change, the value
# just set is kept for this long, so a stale cached read can't flip it back.
MAX_BACKUP_HOLD_SECONDS = 32

# Unique-ID suffixes of every entity that only exists when controls are enabled.
CONTROL_ENTITY_KEYS = (
    "grid_connection",
    "backup_reserve",
    "operating_mode",
    "grid_charging",
    "grid_export",
    "max_backup",
    "max_backup_until",
    "max_backup_ends",
    "storm_watch_active",
)

# Entities from earlier versions that no longer exist. They are removed from the
# registry on setup so they don't linger as unavailable.
LEGACY_ENTITY_KEYS = ("max_backup_duration",)

# Sensor key -> InfluxDB field whose daily integral (in kWh) feeds that sensor
ENERGY_FIELDS: dict[str, str] = {
    "battery_charged": "to_pw",
    "battery_discharged": "from_pw",
    "grid_exported": "to_grid",
    "grid_imported": "from_grid",
    "home_usage": "home",
    "solar_generated": "solar",
}
