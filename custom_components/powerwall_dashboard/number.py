"""Number platform: backup reserve and max backup duration.

These only exist when "Allow controls" is on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_BACKUP_MAX_MINUTES, MAX_BACKUP_MIN_MINUTES
from .coordinator import ControlCoordinator
from .entity import PowerwallControlEntity

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


class BackupReserveNumber(PowerwallControlEntity, NumberEntity):
    """The battery level (%) kept in reserve for backup."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-lock"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, entry, "backup_reserve")

    @property
    def native_value(self) -> float | None:
        """The current backup reserve, read from /pw/get_reserve."""
        return self.control_data.get("reserve")

    async def async_set_native_value(self, value: float) -> None:
        """Send the new reserve to /control/reserve."""
        await self.coordinator.async_set_reserve(value)


class MaxBackupDurationNumber(PowerwallControlEntity, RestoreNumber):
    """How long (in minutes) "Max backup" runs when it is switched on.

    This is a Home Assistant-side setting: the gateway has no endpoint to read
    it back, so it is remembered across restarts instead.
    """

    _attr_native_min_value = MAX_BACKUP_MIN_MINUTES
    _attr_native_max_value = MAX_BACKUP_MAX_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, entry, "max_backup_duration")

    async def async_added_to_hass(self) -> None:
        """Restore the last value the user chose."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.coordinator.max_backup_minutes = min(
                max(last.native_value, MAX_BACKUP_MIN_MINUTES), MAX_BACKUP_MAX_MINUTES
            )

    @property
    def native_value(self) -> float:
        """The duration the Max backup switch will use."""
        return self.coordinator.max_backup_minutes

    async def async_set_native_value(self, value: float) -> None:
        """Remember the new duration (nothing is sent until Max backup is on)."""
        self.coordinator.max_backup_minutes = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control numbers (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities(
        [
            BackupReserveNumber(coordinator, entry),
            MaxBackupDurationNumber(coordinator, entry),
        ]
    )
