"""The Powerwall Dashboard integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ALLOW_CONTROLS,
    CONF_CONTROL_SECRET,
    CONF_INFLUXDB_URL,
    CONF_PYPOWERWALL_URL,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_STRINGS,
    CONF_TEMPERATURE_UNIT,
    CONF_TIMEZONE,
    CONTROL_ENTITY_KEYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TEMPERATURE_UNIT,
    LEGACY_ENTITY_KEYS,
    TEMPERATURE_UNITS,
)
from .coordinator import (
    ControlCoordinator,
    DiagnosticsCoordinator,
    InfluxDbCoordinator,
    PyPowerwallCoordinator,
    UpdateStatusCoordinator,
)
from .services import async_register_services, async_remove_services_if_unused

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


@dataclass
class PowerwallDashboardData:
    """Runtime data for a config entry."""

    powerwall_coordinator: PyPowerwallCoordinator
    influxdb_coordinator: InfluxDbCoordinator
    update_coordinator: UpdateStatusCoordinator
    diagnostics_coordinator: DiagnosticsCoordinator
    control_coordinator: ControlCoordinator | None
    pypowerwall_url: str
    influxdb_url: str
    timezone: str
    scan_interval: int
    show_strings: bool
    temperature_unit: str
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
    show_strings = config.get(CONF_SHOW_STRINGS, False)
    # Entries created before this option existed use Celsius, the gateway's unit.
    temperature_unit = TEMPERATURE_UNITS.get(
        config.get(CONF_TEMPERATURE_UNIT, DEFAULT_TEMPERATURE_UNIT),
        TEMPERATURE_UNITS[DEFAULT_TEMPERATURE_UNIT],
    )

    powerwall_coordinator = PyPowerwallCoordinator(
        hass, entry, config[CONF_PYPOWERWALL_URL], scan_interval, show_strings
    )
    influxdb_coordinator = InfluxDbCoordinator(
        hass,
        entry,
        config[CONF_INFLUXDB_URL],
        config[CONF_TIMEZONE],
        scan_interval,
    )

    update_coordinator = UpdateStatusCoordinator(
        hass, entry, config[CONF_PYPOWERWALL_URL], scan_interval
    )
    diagnostics_coordinator = DiagnosticsCoordinator(
        hass, entry, config[CONF_PYPOWERWALL_URL], scan_interval
    )

    # Control entities exist only when controls are enabled (and have a secret).
    control_secret = config.get(CONF_CONTROL_SECRET)
    control_coordinator: ControlCoordinator | None = None
    if allow_controls and control_secret:
        control_coordinator = ControlCoordinator(
            hass, entry, config[CONF_PYPOWERWALL_URL], control_secret, scan_interval
        )

    # If either source is unreachable, raises ConfigEntryNotReady and HA retries.
    await powerwall_coordinator.async_config_entry_first_refresh()
    await influxdb_coordinator.async_config_entry_first_refresh()
    # Firmware status, diagnostics and controls are nice-to-haves: a failure here
    # must not block setup.
    await update_coordinator.async_refresh()
    await diagnostics_coordinator.async_refresh()
    if control_coordinator is not None:
        await control_coordinator.async_refresh()
    else:
        _remove_entities(hass, entry, CONTROL_ENTITY_KEYS)
    # Drop entities from earlier versions that no longer exist.
    _remove_entities(hass, entry, LEGACY_ENTITY_KEYS)

    entry.runtime_data = PowerwallDashboardData(
        powerwall_coordinator=powerwall_coordinator,
        influxdb_coordinator=influxdb_coordinator,
        update_coordinator=update_coordinator,
        diagnostics_coordinator=diagnostics_coordinator,
        control_coordinator=control_coordinator,
        pypowerwall_url=config[CONF_PYPOWERWALL_URL],
        influxdb_url=config[CONF_INFLUXDB_URL],
        timezone=config[CONF_TIMEZONE],
        scan_interval=scan_interval,
        show_strings=show_strings,
        temperature_unit=temperature_unit,
        allow_controls=allow_controls,
        # Never expose a stale secret when controls are switched off.
        control_secret=config.get(CONF_CONTROL_SECRET) if allow_controls else None,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The Start/Stop Max Backup actions exist while any instance has controls on.
    if control_coordinator is not None:
        async_register_services(hass)

    # Reload whenever options or reconfigured data change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_remove_services_if_unused(hass, entry)
    return unloaded


def _remove_entities(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry, keys: tuple[str, ...]
) -> None:
    """Remove entities whose unique ID ends in one of keys from the registry."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.removeprefix(prefix) in keys:
            registry.async_remove(entity.entity_id)


async def _async_update_listener(
    hass: HomeAssistant, entry: PowerwallDashboardConfigEntry
) -> None:
    """Reload the entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
