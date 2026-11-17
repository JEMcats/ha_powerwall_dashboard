"""Actions (services) for the Powerwall Dashboard integration.

The Start/Stop Max Backup actions only exist while at least one instance has
"Allow controls" on: they are registered when such an instance is set up and
removed when the last one is unloaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MAX_BACKUP_MAX_SECONDS, MAX_BACKUP_MIN_SECONDS

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry
    from .coordinator import ControlCoordinator

SERVICE_START_MAX_BACKUP = "start_max_backup"
SERVICE_STOP_MAX_BACKUP = "stop_max_backup"
ATTR_DURATION = "duration"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

START_MAX_BACKUP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DURATION): vol.All(
            vol.Coerce(int),
            vol.Range(min=MAX_BACKUP_MIN_SECONDS, max=MAX_BACKUP_MAX_SECONDS),
        ),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)
STOP_MAX_BACKUP_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


def _error(key: str) -> ServiceValidationError:
    """Build a translated validation error (see "exceptions" in strings.json)."""
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key)


def _control_entries(
    hass: HomeAssistant, exclude_entry_id: str | None = None
) -> list[PowerwallDashboardConfigEntry]:
    """Loaded instances that have controls enabled."""
    return [
        entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if entry.entry_id != exclude_entry_id
        and entry.runtime_data.control_coordinator is not None
    ]


def _resolve_coordinator(
    hass: HomeAssistant, config_entry_id: str | None
) -> ControlCoordinator:
    """Pick the instance an action should act on.

    With a config_entry_id, that instance is used. Without one, the only
    instance that has controls enabled is used; if there are several, the
    caller has to say which.
    """
    entries = _control_entries(hass)

    if config_entry_id is not None:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise _error("unknown_instance")
        if entry.entry_id not in {e.entry_id for e in entries}:
            raise _error("controls_not_enabled")
        return entry.runtime_data.control_coordinator

    if not entries:
        raise _error("no_control_instance")
    if len(entries) > 1:
        raise _error("multiple_instances")
    return entries[0].runtime_data.control_coordinator


async def _async_start_max_backup(call: ServiceCall) -> None:
    """Start a max backup lasting `duration` seconds."""
    coordinator = _resolve_coordinator(call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    await coordinator.async_start_max_backup_seconds(call.data[ATTR_DURATION])


async def _async_stop_max_backup(call: ServiceCall) -> None:
    """Cancel the current max backup.

    A cancel is always sent, even if Home Assistant doesn't think one is running:
    its view can be up to 30 seconds old, and a backup started from the Tesla app
    wouldn't show yet. If the gateway refuses, its reason is raised as an error.
    """
    coordinator = _resolve_coordinator(call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    await coordinator.async_cancel_max_backup()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the actions (a no-op for any that already exist)."""
    if not hass.services.has_service(DOMAIN, SERVICE_START_MAX_BACKUP):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_MAX_BACKUP,
            _async_start_max_backup,
            schema=START_MAX_BACKUP_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_STOP_MAX_BACKUP):
        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_MAX_BACKUP,
            _async_stop_max_backup,
            schema=STOP_MAX_BACKUP_SCHEMA,
        )


@callback
def async_remove_services_if_unused(
    hass: HomeAssistant, unloading: PowerwallDashboardConfigEntry
) -> None:
    """Remove the actions unless another instance still has controls enabled."""
    if _control_entries(hass, exclude_entry_id=unloading.entry_id):
        return
    hass.services.async_remove(DOMAIN, SERVICE_START_MAX_BACKUP)
    hass.services.async_remove(DOMAIN, SERVICE_STOP_MAX_BACKUP)
