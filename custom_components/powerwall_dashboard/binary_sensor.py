"""Binary sensor platform: Storm Watch active.

Only exists when "Allow controls" is on, since it reads /control/max_backup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ControlCoordinator
from .entity import PowerwallControlEntity, storm_watch_active

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


class StormWatchActiveBinarySensor(PowerwallControlEntity, BinarySensorEntity):
    """On whenever the gateway reports any backup event."""

    _attr_icon = "mdi:weather-lightning"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry, "storm_watch_active")

    @property
    def is_on(self) -> bool | None:
        """True when backup_events is anything other than empty."""
        return storm_watch_active(self.control_data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Storm Watch sensor (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities([StormWatchActiveBinarySensor(coordinator, entry)])
