"""Switch platform: grid connection, max backup and grid charging.

These only exist when "Allow controls" is on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ControlCoordinator
from .entity import PowerwallControlEntity, max_backup_active

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


class GridConnectionSwitch(PowerwallControlEntity, SwitchEntity):
    """Manual grid connection. Off islands the house from the grid.

    The state comes from /pw/is_connected. The server locks islanding for a
    minute after any request, so a second toggle right away is refused.
    """

    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "grid_connection")

    @property
    def is_on(self) -> bool | None:
        """True while connected to the grid."""
        return self.control_data.get("is_connected")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Reconnect to the grid."""
        await self.coordinator.async_set_grid_connected(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disconnect from the grid (go off-grid)."""
        await self.coordinator.async_set_grid_connected(False)


class MaxBackupSwitch(PowerwallControlEntity, SwitchEntity):
    """Max backup (reserves the battery for backup) for a set duration.

    On starts a backup lasting the "Max backup duration" number; off cancels it.
    """

    _attr_icon = "mdi:battery-heart-variant"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "max_backup")

    @property
    def is_on(self) -> bool | None:
        """True while a manual max backup is active."""
        return max_backup_active(self.control_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start max backup for the configured duration."""
        await self.coordinator.async_start_max_backup(
            self.coordinator.max_backup_minutes
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Cancel max backup."""
        await self.coordinator.async_cancel_max_backup()


class GridChargingSwitch(PowerwallControlEntity, SwitchEntity):
    """Whether the battery may charge from the grid."""

    _attr_icon = "mdi:battery-charging-outline"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "grid_charging")

    @property
    def is_on(self) -> bool | None:
        """True if grid charging is allowed."""
        return self.control_data.get("grid_charging")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow grid charging."""
        await self.coordinator.async_set_grid_charging(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Forbid grid charging."""
        await self.coordinator.async_set_grid_charging(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control switches (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities(
        [
            GridConnectionSwitch(coordinator, entry),
            MaxBackupSwitch(coordinator, entry),
            GridChargingSwitch(coordinator, entry),
        ]
    )
