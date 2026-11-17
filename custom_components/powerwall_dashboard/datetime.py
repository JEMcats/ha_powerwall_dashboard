"""Datetime platform: when the next max backup should end.

Only exists when "Allow controls" is on.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .coordinator import ControlCoordinator
from .entity import PowerwallControlEntity

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


class MaxBackupUntilDateTime(PowerwallControlEntity, DateTimeEntity, RestoreEntity):
    """The date and time the next max backup should end.

    This is a Home Assistant-side setting: nothing is sent to the gateway until
    the Max backup switch is turned on, and changing it does not alter a backup
    that is already running. The gateway has no endpoint to read it back, so it is
    remembered across restarts instead.
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, entry, "max_backup_until")

    async def async_added_to_hass(self) -> None:
        """Restore the last time the user chose, unless it has already passed."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        restored = dt_util.parse_datetime(last.state)
        if (
            restored is not None
            and restored.tzinfo is not None
            and restored > dt_util.utcnow()
        ):
            self.coordinator.max_backup_until = restored

    @property
    def native_value(self) -> datetime | None:
        """The chosen end time (unknown until one is set)."""
        return self.coordinator.max_backup_until

    async def async_set_value(self, value: datetime) -> None:
        """Remember the new end time (nothing is sent until Max backup is on)."""
        self.coordinator.max_backup_until = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the max backup end time (only when controls are enabled)."""
    coordinator = entry.runtime_data.control_coordinator
    if coordinator is None:
        return

    async_add_entities([MaxBackupUntilDateTime(coordinator, entry)])
