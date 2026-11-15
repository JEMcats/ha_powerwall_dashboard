"""Shared entity helpers for the Powerwall Dashboard integration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PYPOWERWALL_URL, DOMAIN
from .coordinator import ControlCoordinator

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry


def powerwall_device_info(entry: PowerwallDashboardConfigEntry) -> DeviceInfo:
    """Return the single device that all of this entry's entities belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Powerwall",
        manufacturer="Tesla",
        model="Powerwall",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data.get(CONF_PYPOWERWALL_URL),
    )


# ----------------------------------------------------------------------
# Reading /control/max_backup
#
# {"manual_backup": {"start_time": ..., "duration_seconds": ..., "end_time": ...,
#                    "active": true, "priority": ...},
#  "backup_events": []}
# ----------------------------------------------------------------------
def manual_backup(data: dict[str, Any]) -> dict[str, Any] | None:
    """The manual_backup block, {} if there is none, None if unreadable."""
    max_backup = data.get("max_backup")
    if not isinstance(max_backup, dict):
        return None
    manual = max_backup.get("manual_backup")
    return manual if isinstance(manual, dict) else {}


def max_backup_active(data: dict[str, Any]) -> bool | None:
    """Whether a manual max backup is running (None if unreadable)."""
    manual = manual_backup(data)
    if manual is None:
        return None
    return bool(manual.get("active"))


def max_backup_end(data: dict[str, Any]) -> datetime | None:
    """When the running manual max backup ends; None if none is running.

    end_time is an epoch timestamp in seconds. It is only reported while the
    backup is active, since an old end_time would just be stale history.
    """
    manual = manual_backup(data)
    if not manual or not manual.get("active"):
        return None
    end_time = manual.get("end_time")
    if isinstance(end_time, bool) or not isinstance(end_time, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(end_time, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def storm_watch_active(data: dict[str, Any]) -> bool | None:
    """Storm Watch is active when backup_events holds anything (None if unreadable)."""
    max_backup = data.get("max_backup")
    if not isinstance(max_backup, dict):
        return None
    return bool(max_backup.get("backup_events"))


class PowerwallControlEntity(CoordinatorEntity[ControlCoordinator]):
    """Base class for entities that read or change Powerwall control settings.

    key is the entity's translation key and the suffix of its unique ID (it must
    be listed in CONTROL_ENTITY_KEYS so the entity is removed when controls are
    switched off).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ControlCoordinator,
        entry: PowerwallDashboardConfigEntry,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def control_data(self) -> dict[str, Any]:
        """The coordinator's data (empty if the first read failed)."""
        return self.coordinator.data or {}
