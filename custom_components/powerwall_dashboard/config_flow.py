"""Config, reconfigure and options flows for the PyPowerwall Proxy integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALLOW_CONTROLS,
    CONF_CONTROL_SECRET,
    CONF_INFLUXDB_URL,
    CONF_PYPOWERWALL_URL,
    CONF_SCAN_INTERVAL,
    CONF_TIMEZONE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
ENTRY_TITLE = "PyPowerwall Proxy"


# ----------------------------------------------------------------------
# Shared validation helpers
# ----------------------------------------------------------------------
def _normalize_url(value: str) -> str | None:
    """Return a cleaned http(s) URL without a trailing slash, or None if invalid."""
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return value


async def _async_check_pypowerwall(hass: HomeAssistant, url: str) -> bool:
    """Check that a pypowerwall proxy answers at the given URL."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{url}/version", timeout=REQUEST_TIMEOUT) as resp:
            return resp.status == 200
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not reach pypowerwall at %s: %s", url, err)
        return False


async def _async_check_influxdb(hass: HomeAssistant, url: str) -> bool:
    """Check that InfluxDB answers at the given URL (/ping works on v1 and v2)."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{url}/ping", timeout=REQUEST_TIMEOUT) as resp:
            return resp.status in (200, 204)
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Could not reach InfluxDB at %s: %s", url, err)
        return False


async def _async_validate_urls(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[str | None, str | None, dict[str, str]]:
    """Validate and test both URLs. Returns (pypowerwall_url, influxdb_url, errors)."""
    errors: dict[str, str] = {}
    pw_url = _normalize_url(user_input[CONF_PYPOWERWALL_URL])
    influx_url = _normalize_url(user_input[CONF_INFLUXDB_URL])

    if pw_url is None:
        errors[CONF_PYPOWERWALL_URL] = "invalid_url"
    if influx_url is None:
        errors[CONF_INFLUXDB_URL] = "invalid_url"

    if not errors:
        if not await _async_check_pypowerwall(hass, pw_url):
            errors[CONF_PYPOWERWALL_URL] = "cannot_connect"
        if not await _async_check_influxdb(hass, influx_url):
            errors[CONF_INFLUXDB_URL] = "cannot_connect"

    return pw_url, influx_url, errors


async def _async_valid_timezone(name: str) -> bool:
    """Return True if name is a valid IANA timezone."""
    return await dt_util.async_get_time_zone(name.strip()) is not None


def _url_schema() -> dict[Any, Any]:
    """Schema fields for the two URLs (shared by setup and reconfigure)."""
    return {
        vol.Required(CONF_PYPOWERWALL_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_INFLUXDB_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
    }


def _secret_schema() -> vol.Schema:
    """Schema for the control secret step (shared by setup and options)."""
    return vol.Schema(
        {
            vol.Required(CONF_CONTROL_SECRET): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


def _scan_interval_selector() -> NumberSelector:
    """Selector for the polling interval, in seconds."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=MAX_SCAN_INTERVAL,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


# ----------------------------------------------------------------------
# Initial setup + reconfigure
# ----------------------------------------------------------------------
class PyPowerwallProxyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PyPowerwall Proxy."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return PyPowerwallProxyOptionsFlow()

    # -- Step 1: connection details ------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the pypowerwall URL, InfluxDB URL, timezone and controls toggle."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pw_url, influx_url, errors = await _async_validate_urls(
                self.hass, user_input
            )
            tz_name = user_input[CONF_TIMEZONE].strip()
            if not await _async_valid_timezone(tz_name):
                errors[CONF_TIMEZONE] = "invalid_timezone"

            if not errors:
                await self.async_set_unique_id(pw_url)
                self._abort_if_unique_id_configured()

                self._data = {
                    CONF_PYPOWERWALL_URL: pw_url,
                    CONF_INFLUXDB_URL: influx_url,
                    CONF_TIMEZONE: tz_name,
                    CONF_ALLOW_CONTROLS: user_input[CONF_ALLOW_CONTROLS],
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }

                if self._data[CONF_ALLOW_CONTROLS]:
                    return await self.async_step_controls()

                return self.async_create_entry(title=ENTRY_TITLE, data=self._data)

        schema = vol.Schema(
            {
                **_url_schema(),
                vol.Required(CONF_TIMEZONE): TextSelector(),
                vol.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): _scan_interval_selector(),
                vol.Required(CONF_ALLOW_CONTROLS, default=False): BooleanSelector(),
            }
        )

        suggested = user_input or {
            CONF_PYPOWERWALL_URL: "http://",
            CONF_INFLUXDB_URL: "http://",
            CONF_TIMEZONE: self.hass.config.time_zone,
        }

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    # -- Step 2: control secret (only when controls are allowed) -------
    async def async_step_controls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the control secret (PW_CONTROL_SECRET from the docker env)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            secret = user_input[CONF_CONTROL_SECRET].strip()
            if not secret:
                errors[CONF_CONTROL_SECRET] = "empty_secret"
            else:
                self._data[CONF_CONTROL_SECRET] = secret
                return self.async_create_entry(title=ENTRY_TITLE, data=self._data)

        return self.async_show_form(
            step_id="controls", data_schema=_secret_schema(), errors=errors
        )

    # -- Reconfigure: change the connection URLs -----------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the pypowerwall and InfluxDB URLs."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            pw_url, influx_url, errors = await _async_validate_urls(
                self.hass, user_input
            )

            # The pypowerwall URL is the unique ID; don't collide with another entry.
            if not errors:
                for other in self._async_current_entries(include_ignore=False):
                    if other.entry_id != entry.entry_id and other.unique_id == pw_url:
                        errors[CONF_PYPOWERWALL_URL] = "already_configured"
                        break

            if not errors:
                # The entry's update listener (see __init__.py) reloads it.
                self.hass.config_entries.async_update_entry(
                    entry,
                    unique_id=pw_url,
                    data={
                        **entry.data,
                        CONF_PYPOWERWALL_URL: pw_url,
                        CONF_INFLUXDB_URL: influx_url,
                    },
                )
                return self.async_abort(reason="reconfigure_successful")

        suggested = user_input or {
            CONF_PYPOWERWALL_URL: entry.data[CONF_PYPOWERWALL_URL],
            CONF_INFLUXDB_URL: entry.data[CONF_INFLUXDB_URL],
        }

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_url_schema()), suggested
            ),
            errors=errors,
        )


# ----------------------------------------------------------------------
# Options flow
# ----------------------------------------------------------------------
class PyPowerwallProxyOptionsFlow(OptionsFlow):
    """Handle options: timezone, allow controls and the control secret."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._options: dict[str, Any] = {}

    @property
    def _current(self) -> dict[str, Any]:
        """Current effective settings (options override the original data)."""
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit timezone and the allow controls toggle."""
        errors: dict[str, str] = {}
        current = self._current

        if user_input is not None:
            tz_name = user_input[CONF_TIMEZONE].strip()
            if not await _async_valid_timezone(tz_name):
                errors[CONF_TIMEZONE] = "invalid_timezone"
            else:
                self._options = {
                    CONF_TIMEZONE: tz_name,
                    CONF_ALLOW_CONTROLS: user_input[CONF_ALLOW_CONTROLS],
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }
                if self._options[CONF_ALLOW_CONTROLS]:
                    return await self.async_step_controls()
                # Controls off: the secret is intentionally not carried over.
                return self.async_create_entry(data=self._options)

        schema = vol.Schema(
            {
                vol.Required(CONF_TIMEZONE): TextSelector(),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): _scan_interval_selector(),
                vol.Required(
                    CONF_ALLOW_CONTROLS,
                    default=current.get(CONF_ALLOW_CONTROLS, False),
                ): BooleanSelector(),
            }
        )

        suggested = user_input or {CONF_TIMEZONE: current.get(CONF_TIMEZONE)}

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_controls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the control secret."""
        errors: dict[str, str] = {}

        if user_input is not None:
            secret = user_input[CONF_CONTROL_SECRET].strip()
            if not secret:
                errors[CONF_CONTROL_SECRET] = "empty_secret"
            else:
                return self.async_create_entry(
                    data={**self._options, CONF_CONTROL_SECRET: secret}
                )

        suggested = user_input or {
            CONF_CONTROL_SECRET: self._current.get(CONF_CONTROL_SECRET, "")
        }

        return self.async_show_form(
            step_id="controls",
            data_schema=self.add_suggested_values_to_schema(
                _secret_schema(), suggested
            ),
            errors=errors,
        )
