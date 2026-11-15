"""Sensors for the Powerwall Dashboard integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_STRING_NAMES
from .coordinator import ControlCoordinator, InfluxDbCoordinator, PyPowerwallCoordinator
from .entity import PowerwallControlEntity, max_backup_end, powerwall_device_info

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


# ----------------------------------------------------------------------
# Live sensors (pypowerwall)
# ----------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class PowerwallSensorDescription(SensorEntityDescription):
    """Describes a sensor whose value is read out of the pypowerwall data."""

    value_fn: Callable[[dict[str, Any]], StateType]


def _power_kw(section: str) -> Callable[[dict[str, Any]], float | None]:
    """Return a value_fn reading aggregates[section].instant_power, in kW.

    section is the pypowerwall meter name: solar, battery, site (grid) or load.
    """

    def _get(data: dict[str, Any]) -> float | None:
        try:
            return data["aggregates"][section]["instant_power"] / 1000
        except (KeyError, TypeError):
            return None

    return _get


def _percentage_charged(data: dict[str, Any]) -> float | None:
    """Battery state of energy, in percent."""
    try:
        return data["soe"]["percentage"]
    except (KeyError, TypeError):
        return None


GRID_STATUS_MAP = {
    "SystemGridConnected": "connected",
    "SystemIslandedActive": "disconnected",
    "SystemTransitionToGrid": "transitioning",
}


def _grid_status(data: dict[str, Any]) -> str | None:
    """Map pypowerwall's grid status to a sensor state (None = unknown)."""
    try:
        return GRID_STATUS_MAP.get(data["grid_status"]["grid_status"])
    except (KeyError, TypeError):
        return None


def _time_remaining(data: dict[str, Any]) -> float | None:
    """Time until depletion, in hours."""
    try:
        return data["time_remaining"]
    except (KeyError, TypeError):
        return None


POWERWALL_SENSORS: tuple[PowerwallSensorDescription, ...] = (
    PowerwallSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_power_kw("solar"),
    ),
    PowerwallSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        icon="mdi:home-battery",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_power_kw("battery"),
    ),
    PowerwallSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        icon="mdi:transmission-tower",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        # pypowerwall calls the grid meter "site".
        value_fn=_power_kw("site"),
    ),
    PowerwallSensorDescription(
        key="load_power",
        translation_key="load_power",
        icon="mdi:power-plug",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_power_kw("load"),
    ),
    PowerwallSensorDescription(
        key="percentage_charged",
        translation_key="percentage_charged",
        # BATTERY device class gives a level-aware icon automatically.
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_percentage_charged,
    ),
    PowerwallSensorDescription(
        key="grid_status",
        translation_key="grid_status",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.ENUM,
        options=list(GRID_STATUS_MAP.values()),
        value_fn=_grid_status,
    ),
    PowerwallSensorDescription(
        key="time_remaining",
        translation_key="time_remaining",
        icon="mdi:battery-clock-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_time_remaining,
    ),
)


class PowerwallSensor(CoordinatorEntity[PyPowerwallCoordinator], SensorEntity):
    """A live sensor backed by the pypowerwall coordinator."""

    entity_description: PowerwallSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PyPowerwallCoordinator,
        description: PowerwallSensorDescription,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)


# ----------------------------------------------------------------------
# Daily energy sensors (InfluxDB)
# ----------------------------------------------------------------------
def _energy(key: str, icon: str) -> SensorEntityDescription:
    """Describe a daily energy total. key must be a key of ENERGY_FIELDS."""
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        icon=icon,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        # Totals reset at local midnight, which total_increasing handles.
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    )


ENERGY_SENSORS: tuple[SensorEntityDescription, ...] = (
    _energy("battery_charged", "mdi:battery-arrow-up"),
    _energy("battery_discharged", "mdi:battery-arrow-down"),
    _energy("grid_exported", "mdi:transmission-tower-export"),
    _energy("grid_imported", "mdi:transmission-tower-import"),
    _energy("home_usage", "mdi:home-lightning-bolt"),
    _energy("solar_generated", "mdi:solar-power-variant"),
)


class InfluxEnergySensor(CoordinatorEntity[InfluxDbCoordinator], SensorEntity):
    """A daily energy total backed by the InfluxDB coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InfluxDbCoordinator,
        description: SensorEntityDescription,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return today's total in kWh."""
        return self.coordinator.data.get(self.entity_description.key)


# ----------------------------------------------------------------------
# Solar string sensors (pypowerwall /strings, opt-in via "Show strings")
# ----------------------------------------------------------------------
class PowerwallStringSensor(CoordinatorEntity[PyPowerwallCoordinator], SensorEntity):
    """Power from one solar string (A, B, C, ...), in watts."""

    _attr_has_entity_name = True
    _attr_translation_key = "string_power"
    _attr_icon = "mdi:solar-panel"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: PyPowerwallCoordinator,
        string_name: str,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._string_name = string_name
        self._attr_unique_id = f"{entry.entry_id}_string_{string_name.lower()}_power"
        self._attr_translation_placeholders = {"string": string_name}
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def _string(self) -> dict[str, Any] | None:
        """This string's block of the /strings response, if present."""
        strings = (self.coordinator.data or {}).get("strings")
        if not isinstance(strings, dict):
            return None
        value = strings.get(self._string_name)
        return value if isinstance(value, dict) else None

    @property
    def native_value(self) -> float | None:
        """Return the string's power in watts."""
        string = self._string
        if string is None:
            return None
        power = string.get("Power")
        # The gateway reports float noise like 183.74999999999991.
        return round(power, 2) if isinstance(power, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the rest of the string's readings as attributes."""
        string = self._string
        if string is None:
            return None
        current = string.get("Current")
        return {
            "state": string.get("State"),
            "voltage": string.get("Voltage"),
            "current": round(current, 2) if isinstance(current, (int, float)) else current,
            "connected": string.get("Connected"),
        }


def _remove_string_entities(hass: HomeAssistant, entry: PowerwallDashboardConfigEntry) -> None:
    """Remove string entities from the registry (used when the option is off)."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_string_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.startswith(prefix):
            registry.async_remove(entity.entity_id)


# ----------------------------------------------------------------------
# Max backup end time (only when controls are enabled)
# ----------------------------------------------------------------------
class MaxBackupEndsSensor(PowerwallControlEntity, SensorEntity):
    """When the current manual max backup ends, as a timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "max_backup_ends")

    @property
    def native_value(self) -> datetime | None:
        """The end time while max backup is active, otherwise unknown."""
        return max_backup_end(self.control_data)


# ----------------------------------------------------------------------
# Platform setup
# ----------------------------------------------------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for a config entry."""
    data = entry.runtime_data

    entities: list[SensorEntity] = [
        PowerwallSensor(data.powerwall_coordinator, description, entry)
        for description in POWERWALL_SENSORS
    ]
    entities.extend(
        InfluxEnergySensor(data.influxdb_coordinator, description, entry)
        for description in ENERGY_SENSORS
    )
    if data.show_strings:
        strings = data.powerwall_coordinator.data.get("strings")
        names = (
            sorted(name for name, value in strings.items() if isinstance(value, dict))
            if isinstance(strings, dict)
            else []
        )
        # If /strings couldn't be read at startup, still create A-F.
        for name in names or DEFAULT_STRING_NAMES:
            entities.append(
                PowerwallStringSensor(data.powerwall_coordinator, name, entry)
            )
    else:
        # Switched off: drop any string entities left over from when it was on.
        _remove_string_entities(hass, entry)

    if data.control_coordinator is not None:
        entities.append(MaxBackupEndsSensor(data.control_coordinator, entry))

    async_add_entities(entities)
