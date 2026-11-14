"""Constants for the Powerwall Dashboard integration."""

DOMAIN = "powerwall_dashboard"

CONF_PYPOWERWALL_URL = "pypowerwall_url"
CONF_INFLUXDB_URL = "influxdb_url"
CONF_TIMEZONE = "timezone"
CONF_ALLOW_CONTROLS = "allow_controls"
CONF_CONTROL_SECRET = "control_secret"
CONF_SCAN_INTERVAL = "scan_interval"

# pypowerwall proxy endpoints
PYPOWERWALL_AGGREGATES_PATH = "/api/meters/aggregates"
PYPOWERWALL_SOE_PATH = "/api/system_status/soe"
PYPOWERWALL_GRID_STATUS_PATH = "/api/system_status/grid_status"

# InfluxDB (v1) location of the Powerwall-Dashboard data
INFLUXDB_DATABASE = "powerwall"
INFLUXDB_RETENTION_POLICY = "autogen"
INFLUXDB_MEASUREMENT = "http"

# Polling interval in seconds, shared by both coordinators and user-configurable.
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 3600

# Sensor key -> InfluxDB field whose daily integral (in kWh) feeds that sensor
ENERGY_FIELDS: dict[str, str] = {
    "battery_charged": "to_pw",
    "battery_discharged": "from_pw",
    "grid_exported": "to_grid",
    "grid_imported": "from_grid",
    "home_usage": "home",
    "solar_generated": "solar",
}
