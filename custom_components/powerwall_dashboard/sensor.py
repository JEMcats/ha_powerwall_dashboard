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
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_STRING_NAMES, DOMAIN, GRID_STATUS_MAP
from .coordinator import (
    ControlCoordinator,
    DiagnosticsCoordinator,
    InfluxDbCoordinator,
    PyPowerwallCoordinator,
)
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


def _voltage(section: str) -> Callable[[dict[str, Any]], float | None]:
    """Return a value_fn reading aggregates[section].instant_average_voltage, in V.

    section is the pypowerwall meter name: solar, battery, site (grid) or load.
    """

    def _get(data: dict[str, Any]) -> float | None:
        try:
            value = data["aggregates"][section]["instant_average_voltage"]
        except (KeyError, TypeError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    return _get


def _percentage_charged(data: dict[str, Any]) -> float | None:
    """Battery state of energy, in percent."""
    try:
        return data["soe"]["percentage"]
    except (KeyError, TypeError):
        return None


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
    PowerwallSensorDescription(
        key="load_voltage",
        translation_key="load_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_voltage("load"),
    ),
    PowerwallSensorDescription(
        key="grid_voltage",
        translation_key="grid_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        # pypowerwall calls the grid meter "site".
        value_fn=_voltage("site"),
    ),
    PowerwallSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_voltage("battery"),
    ),
    PowerwallSensorDescription(
        key="solar_voltage",
        translation_key="solar_voltage",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_voltage("solar"),
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
# Per-Powerwall and combined diagnostics (/pod, /temps/pw, /fans/pw)
#
# Powerwalls are numbered PW1, PW2, ... by pypowerwall, leader first. They are
# discovered from the data, so a Powerwall that wasn't reachable at startup still
# gets its sensors as soon as it shows up.
# ----------------------------------------------------------------------
UNIT_RPM = "rpm"


@dataclass(frozen=True, kw_only=True)
class DiagnosticSensorDescription(SensorEntityDescription):
    """Describes a diagnostic sensor read from a Powerwall's or the combined block."""

    value_fn: Callable[[dict[str, Any]], float | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Whether a Powerwall's block has the data this sensor needs, so e.g. a
    # Powerwall 2 (no fan data) doesn't get a permanently empty fan sensor.
    applies_fn: Callable[[dict[str, Any]], bool] = lambda block: True


def _round(value: Any, digits: int) -> Any:
    """Round a number for display in an attribute; pass anything else through."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, digits)
    return value


def _capacity_attrs(unit: dict[str, Any]) -> dict[str, Any]:
    """Which Powerwall this is, and the published capacity it is compared to."""
    return {
        "model": unit.get("model"),
        "device": unit.get("name"),
        "spec_kwh": unit.get("spec_kwh"),
    }


def _deviation_attrs(block: dict[str, Any]) -> dict[str, Any]:
    """The published capacity and the difference from it, in kWh."""
    return {
        "spec_kwh": block.get("spec_kwh"),
        "difference_kwh": _round(block.get("difference_kwh"), 3),
    }


def _fan_attrs(unit: dict[str, Any]) -> dict[str, Any]:
    """Each of this Powerwall's fans (the state is their average speed)."""
    attrs: dict[str, Any] = {}
    for fan in unit.get("fans") or []:
        attrs[f"fan_{fan['slot']}_rpm"] = fan.get("rpm")
        attrs[f"fan_{fan['slot']}_duty_percent"] = fan.get("duty")
    return attrs


UNIT_SENSORS: tuple[DiagnosticSensorDescription, ...] = (
    DiagnosticSensorDescription(
        key="temperature",
        translation_key="powerwall_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda unit: unit.get("temperature_c"),
        applies_fn=lambda unit: unit["has_temperature"],
    ),
    DiagnosticSensorDescription(
        key="fan_speed",
        translation_key="powerwall_fan_speed",
        icon="mdi:fan",
        native_unit_of_measurement=UNIT_RPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda unit: unit.get("fan_rpm"),
        attrs_fn=_fan_attrs,
        applies_fn=lambda unit: unit["has_fans"],
    ),
    DiagnosticSensorDescription(
        key="capacity",
        translation_key="powerwall_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda unit: unit.get("capacity_kwh"),
        attrs_fn=_capacity_attrs,
        applies_fn=lambda unit: unit["has_pod"],
    ),
    DiagnosticSensorDescription(
        key="charge",
        translation_key="powerwall_charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda unit: unit.get("charge_kwh"),
        applies_fn=lambda unit: unit["has_pod"],
    ),
    DiagnosticSensorDescription(
        key="capacity_deviation",
        translation_key="powerwall_capacity_deviation",
        icon="mdi:battery-heart-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda unit: unit.get("deviation_percent"),
        attrs_fn=_deviation_attrs,
        applies_fn=lambda unit: unit["has_pod"],
    ),
)

COMBINED_SENSORS: tuple[DiagnosticSensorDescription, ...] = (
    DiagnosticSensorDescription(
        key="capacity",
        translation_key="combined_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda combined: combined.get("capacity_kwh"),
    ),
    DiagnosticSensorDescription(
        key="charge",
        translation_key="combined_charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda combined: combined.get("charge_kwh"),
    ),
    DiagnosticSensorDescription(
        key="capacity_deviation",
        translation_key="combined_capacity_deviation",
        icon="mdi:battery-heart-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda combined: combined.get("deviation_percent"),
        attrs_fn=_deviation_attrs,
    ),
)


class PowerwallDiagnosticSensor(
    CoordinatorEntity[DiagnosticsCoordinator], SensorEntity
):
    """A diagnostic sensor for one Powerwall, or for the whole system.

    index is the Powerwall's number (1 is the leader), or None for the combined
    sensors. temperature_unit, for temperature sensors, is the display unit chosen
    in the integration's options.
    """

    entity_description: DiagnosticSensorDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DiagnosticsCoordinator,
        description: DiagnosticSensorDescription,
        entry: PowerwallDashboardConfigEntry,
        index: int | None,
        temperature_unit: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._index = index
        scope = "combined" if index is None else f"pw{index}"
        self._attr_unique_id = f"{entry.entry_id}_{scope}_{description.key}"
        if index is not None:
            self._attr_translation_placeholders = {"powerwall": f"PW{index}"}
        if temperature_unit is not None:
            # Used when the entity is first registered; _apply_temperature_unit
            # handles entities that already exist.
            self._attr_suggested_unit_of_measurement = temperature_unit
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def _block(self) -> dict[str, Any] | None:
        """This Powerwall's block of the data, or the combined block."""
        data = self.coordinator.data or {}
        if self._index is None:
            return data.get("combined")
        return (data.get("powerwalls") or {}).get(self._index)

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        block = self._block
        return self.entity_description.value_fn(block) if block else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra details, if this sensor has any."""
        block = self._block
        if not block or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(block)


@callback
def _apply_temperature_unit(hass: HomeAssistant, unique_id: str, unit: str) -> None:
    """Make an already-registered temperature sensor display in the chosen unit.

    Home Assistant normally shows temperatures in its own unit system, and only
    honours a sensor's suggested unit the first time it is registered. Setting the
    entity's unit option is what makes a later change to the integration's
    Temperature unit setting take effect.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is None or (entry := registry.async_get(entity_id)) is None:
        return  # not registered yet: the suggested unit covers it
    options = dict(entry.options.get("sensor", {}))
    if options.get("unit_of_measurement") == unit:
        return
    options["unit_of_measurement"] = unit
    registry.async_update_entity_options(entity_id, "sensor", options)


@callback
def _async_track_diagnostics(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add diagnostic sensors now, and for any Powerwall that appears later."""
    data = entry.runtime_data
    coordinator = data.diagnostics_coordinator
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        diagnostics = coordinator.data or {}
        new: list[PowerwallDiagnosticSensor] = []

        for index, unit in sorted((diagnostics.get("powerwalls") or {}).items()):
            for description in UNIT_SENSORS:
                unique_key = f"pw{index}_{description.key}"
                if unique_key in known or not description.applies_fn(unit):
                    continue
                known.add(unique_key)
                is_temperature = description.key == "temperature"
                sensor = PowerwallDiagnosticSensor(
                    coordinator,
                    description,
                    entry,
                    index,
                    data.temperature_unit if is_temperature else None,
                )
                if is_temperature:
                    _apply_temperature_unit(
                        hass, sensor.unique_id, data.temperature_unit
                    )
                new.append(sensor)

        # The combined sensors need at least one Powerwall reporting pod data.
        if (diagnostics.get("combined") or {}).get("count"):
            for description in COMBINED_SENSORS:
                unique_key = f"combined_{description.key}"
                if unique_key in known:
                    continue
                known.add(unique_key)
                new.append(
                    PowerwallDiagnosticSensor(coordinator, description, entry, None)
                )

        if new:
            async_add_entities(new)

    _add_new()
    # Also keeps the coordinator polling, so Powerwalls are discovered over time.
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


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
    _async_track_diagnostics(hass, entry, async_add_entities)
