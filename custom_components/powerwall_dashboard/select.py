"""Select platform: operating mode and grid export.

These only exist when "Allow controls" is on. The options are the values the
gateway uses; the friendly labels ("Self-Powered", "Solar Only", ...) come from
the translations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import GRID_EXPORT_MODES, OPERATING_MODES
from .coordinator import ControlCoordinator
from .entity import PowerwallControlEntity

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


class OperatingModeSelect(PowerwallControlEntity, SelectEntity):
    """Self-Powered, Time-Based Control or Backup-Only."""

    _attr_options = OPERATING_MODES
    _attr_icon = "mdi:cog"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, entry, "operating_mode")

    @property
    def current_option(self) -> str | None:
        """The mode read from /pw/get_mode (None if it isn't one we know)."""
        mode = self.control_data.get("mode")
        return mode if mode in OPERATING_MODES else None

    async def async_select_option(self, option: str) -> None:
        """Send the new mode to /control/mode."""
        await self.coordinator.async_set_mode(option)


class GridExportSelect(PowerwallControlEntity, SelectEntity):
    """Solar and Battery, Solar Only or Off."""

    _attr_options = GRID_EXPORT_MODES
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, entry, "grid_export")

    @property
    def current_option(self) -> str | None:
        """The rule read from /control/grid_export (None if unrecognized)."""
        value = self.control_data.get("grid_export")
        return value if value in GRID_EXPORT_MODES else None

    async def async_select_option(self, option: str) -> None:
        """Send the new rule to /control/grid_export."""
        await self.coordinator.async_set_grid_export(option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control selects (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities(
        [
            OperatingModeSelect(coordinator, entry),
            GridExportSelect(coordinator, entry),
        ]
    )
