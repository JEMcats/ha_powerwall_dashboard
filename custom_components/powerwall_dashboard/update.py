"""Update platform for the Powerwall Dashboard integration.

Shows the gateway's firmware version and whether an update is on its way, using
the proxy's /api/system/update/status. This entity is read-only: the gateway
installs updates itself, so there is nothing to trigger from Home Assistant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import UpdateStatusCoordinator
from .entity import powerwall_device_info

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry

# The endpoint reports the *current* version but not the version being fetched.
# While an update is pending we show this placeholder as the "latest version" so
# Home Assistant flags an update as available.
PENDING_VERSION = "Update available"

# "state" values that mean a firmware update is on its way, with a summary for
# each. These come from community documentation of the Powerwall gateway API;
# any other state (including ones we haven't seen) is treated as up to date:
#   /update_succeeded, /update_failed ("failed, or not required"),
#   /clear_update_status (checking for an update), /update_unknown
DOWNLOADING_STATE = "/download"
PENDING_SUMMARIES: dict[str, str] = {
    DOWNLOADING_STATE: "A firmware update is being downloaded.",
    "/update_staged": "A firmware update is staged and waiting to be applied.",
    "/update_downloaded": "A firmware update has been downloaded and is ready to install.",
}
OFFLINE_SUMMARY = "An offline firmware update is being applied."


def _state(data: dict[str, Any] | None) -> str | None:
    """The raw update state, e.g. "/update_succeeded"."""
    state = (data or {}).get("state")
    return state if isinstance(state, str) else None


def _offline_updating(data: dict[str, Any] | None) -> bool:
    """True if the gateway reports an offline update in progress."""
    return bool((data or {}).get("offline_updating"))


def _update_pending(data: dict[str, Any] | None) -> bool:
    """True if a firmware update is downloading, staged, or being applied."""
    return _state(data) in PENDING_SUMMARIES or _offline_updating(data)


def _in_progress(data: dict[str, Any] | None) -> bool:
    """True while an update is actively being downloaded or applied."""
    return _state(data) == DOWNLOADING_STATE or _offline_updating(data)


def _release_summary(data: dict[str, Any] | None) -> str | None:
    """A short human-readable description of the pending update, if any."""
    summary = PENDING_SUMMARIES.get(_state(data) or "")
    if summary is None and _offline_updating(data):
        return OFFLINE_SUMMARY
    return summary


def _last_status_time(data: dict[str, Any] | None) -> str | None:
    """last_status_time (epoch milliseconds) as an ISO 8601 UTC timestamp."""
    millis = (data or {}).get("last_status_time")
    if isinstance(millis, bool) or not isinstance(millis, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


class PowerwallFirmwareUpdate(CoordinatorEntity[UpdateStatusCoordinator], UpdateEntity):
    """The Powerwall gateway firmware."""

    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_title = "Powerwall firmware"
    # No INSTALL feature: the gateway updates itself.
    _attr_supported_features = UpdateEntityFeature.PROGRESS

    def __init__(
        self,
        coordinator: UpdateStatusCoordinator,
        entry: PowerwallDashboardConfigEntry,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        self._attr_device_info = powerwall_device_info(entry)

    @property
    def installed_version(self) -> str | None:
        """The firmware version currently installed, e.g. "26.34.3 f2e0e391"."""
        version = (self.coordinator.data or {}).get("version")
        return version if isinstance(version, str) and version else None

    @property
    def latest_version(self) -> str | None:
        """Same as installed when up to date; a placeholder while one is pending."""
        installed = self.installed_version
        if installed is None:
            return None
        return PENDING_VERSION if _update_pending(self.coordinator.data) else installed

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Any difference means an update is pending (the placeholder isn't a version)."""
        return latest_version != installed_version

    @property
    def in_progress(self) -> bool:
        """True while an update is being downloaded or applied."""
        return _in_progress(self.coordinator.data)

    @property
    def release_summary(self) -> str | None:
        """Describe the pending update."""
        return _release_summary(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the rest of the gateway's update status."""
        data = self.coordinator.data
        if not data:
            return None
        info = data.get("info")
        return {
            "update_state": data.get("state"),
            "update_status": info.get("status") if isinstance(info, dict) else None,
            "last_status_time": _last_status_time(data),
            "offline_updating": data.get("offline_updating"),
            # The gateway reports "" when there's no error.
            "offline_update_error": data.get("offline_update_error") or None,
            "estimated_bytes_per_second": data.get("estimated_bytes_per_second"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerwallDashboardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the firmware update entity for a config entry."""
    async_add_entities(
        [PowerwallFirmwareUpdate(entry.runtime_data.update_coordinator, entry)]
    )
