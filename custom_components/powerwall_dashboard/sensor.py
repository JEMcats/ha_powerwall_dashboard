"""Sensors for the Powerwall Dashboard integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PYPOWERWALL_URL, DOMAIN
from .coordinator import InfluxDbCoordinator, PyPowerwallCoordinator

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


def _device_info(entry: PowerwallDashboardConfigEntry) -> DeviceInfo:
    """Return the single device that all of this entry's sensors belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Powerwall",
        manufacturer="Tesla",
        model="Powerwall",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data.get(CONF_PYPOWERWALL_URL),
    )


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
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return today's total in kWh."""
        return self.coordinator.data.get(self.entity_description.key)


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
    async_add_entities(entities)
