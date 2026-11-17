"""Number platform: backup reserve.

Only exists when "Allow controls" is on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control numbers (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities([BackupReserveNumber(coordinator, entry)])
