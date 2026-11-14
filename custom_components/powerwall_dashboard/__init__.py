"""The Powerwall Dashboard integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALLOW_CONTROLS,
    CONF_CONTROL_SECRET,
    CONF_INFLUXDB_URL,
    CONF_PYPOWERWALL_URL,
    CONF_SCAN_INTERVAL,
    CONF_TIMEZONE,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import InfluxDbCoordinator, PyPowerwallCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


@dataclass
class PowerwallDashboardData:
    """Runtime data for a config entry."""

    powerwall_coordinator: PyPowerwallCoordinator
    influxdb_coordinator: InfluxDbCoordinator
    pypowerwall_url: str
    influxdb_url: str
    timezone: str
    scan_interval: int
    allow_controls: bool
    control_secret: str | None


type PowerwallDashboardConfigEntry = ConfigEntry[PowerwallDashboardData]


async def async_setup_entry(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry
) -> bool:
    """Set up Powerwall Dashboard from a config entry."""
    # Options (timezone, controls, secret) override the originally entered data.
    config = {**entry.data, **entry.options}
    allow_controls = config.get(CONF_ALLOW_CONTROLS, False)
    # Entries created before this option existed fall back to the default.
    scan_interval = int(config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    powerwall_coordinator = PyPowerwallCoordinator(
        hass, entry, config[CONF_PYPOWERWALL_URL], scan_interval
    )
    influxdb_coordinator = InfluxDbCoordinator(
        hass,
        entry,
        config[CONF_INFLUXDB_URL],
        config[CONF_TIMEZONE],
        scan_interval,
    )

    # If either source is unreachable, raises ConfigEntryNotReady and HA retries.
    await powerwall_coordinator.async_config_entry_first_refresh()
    await influxdb_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = PowerwallDashboardData(
        powerwall_coordinator=powerwall_coordinator,
        influxdb_coordinator=influxdb_coordinator,
        pypowerwall_url=config[CONF_PYPOWERWALL_URL],
        influxdb_url=config[CONF_INFLUXDB_URL],
        timezone=config[CONF_TIMEZONE],
        scan_interval=scan_interval,
        allow_controls=allow_controls,
        # Never expose a stale secret when controls are switched off.
        control_secret=config.get(CONF_CONTROL_SECRET) if allow_controls else None,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload whenever options or reconfigured data change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry
) -> None:
    """Reload the entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
