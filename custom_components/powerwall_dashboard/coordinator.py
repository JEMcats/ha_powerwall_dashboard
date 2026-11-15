"""Data update coordinators for the Powerwall Dashboard integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONTROL_GRID_CHARGING_PATH,
    CONTROL_GRID_EXPORT_PATH,
    CONTROL_ISLANDING_PATH,
    CONTROL_MAX_BACKUP_PATH,
    CONTROL_MODE_PATH,
    CONTROL_RESERVE_PATH,
    DEFAULT_MAX_BACKUP_MINUTES,
    DOMAIN,
    ENERGY_FIELDS,
    INFLUXDB_DATABASE,
    INFLUXDB_MEASUREMENT,
    INFLUXDB_RETENTION_POLICY,
    MAX_BACKUP_MIN_SECONDS,
    PYPOWERWALL_AGGREGATES_PATH,
    PYPOWERWALL_GET_MODE_PATH,
    PYPOWERWALL_GET_RESERVE_PATH,
    PYPOWERWALL_GRID_STATUS_PATH,
    PYPOWERWALL_IS_CONNECTED_PATH,
    PYPOWERWALL_SOE_PATH,
    PYPOWERWALL_STRINGS_PATH,
    PYPOWERWALL_TIME_REMAINING_PATH,
    PYPOWERWALL_UPDATE_STATUS_PATH,
    SCAN_INTERVAL_CONTROL,
    SCAN_INTERVAL_UPDATE,
)

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry

_LOGGER = logging.getLogger(__name__)

POWERWALL_TIMEOUT = aiohttp.ClientTimeout(total=8)
# Integrating a full day of data can take a few seconds on a busy database.
INFLUXDB_TIMEOUT = aiohttp.ClientTimeout(total=30)
# Control commands can take a moment on the gateway (islanding, max backup).
CONTROL_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _as_float(value: Any) -> float | None:
    """Return value as a float, or None if it isn't a usable number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_time_remaining(raw: Any) -> float | None:
    """Extract hours from the /pw/get_time_remaining response.

    The proxy returns {"time_remaining": 11.23}; a bare number is also accepted.
    """
    if isinstance(raw, dict):
        raw = raw.get("time_remaining")
    return _as_float(raw)


def _as_bool(value: Any) -> bool | None:
    """Return value as a bool, or None if it isn't clearly true or false."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _as_str(value: Any) -> str | None:
    """Return value if it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def _field(payload: Any, key: str) -> Any:
    """Return payload[key] if payload is a dict, else None."""
    return payload.get(key) if isinstance(payload, dict) else None


def _build_control_data(
    is_connected: Any,
    reserve: Any,
    mode: Any,
    grid_charging: Any,
    grid_export: Any,
    max_backup: Any,
) -> dict[str, Any]:
    """Turn the raw control responses into the coordinator's data dict.

    Each response is a small JSON object, e.g. {"is_connected": true} or
    {"reserve": 20}. A response that failed (None) leaves its value None.
    """
    return {
        "is_connected": _as_bool(_field(is_connected, "is_connected")),
        "reserve": _as_float(_field(reserve, "reserve")),
        "mode": _as_str(_field(mode, "mode")),
        "grid_charging": _as_bool(_field(grid_charging, "grid_charging")),
        "grid_export": _as_str(_field(grid_export, "grid_export")),
        "max_backup": max_backup if isinstance(max_backup, dict) else None,
    }


def _control_error(status: int, payload: Any, text: str) -> str | None:
    """Return an error message if a control response means the command failed.

    Failures show up as an HTTP error (FastAPI puts the reason in "detail") or as
    a 200 carrying {"error": ...} / {"unauthorized": ...} like the old proxy.
    """
    detail = None
    if isinstance(payload, dict):
        for key in ("error", "unauthorized", "detail"):
            if payload.get(key):
                detail = str(payload[key])
                break

    if status in (401, 403) or (
        isinstance(payload, dict) and payload.get("unauthorized")
    ):
        return (
            f"pypowerwall refused the command (HTTP {status}). Check that the "
            "Control Secret matches PW_CONTROL_SECRET on your pypowerwall server."
        )
    if status >= 400:
        return f"pypowerwall returned HTTP {status}: {detail or text[:200] or 'no details'}"
    if detail:
        return f"pypowerwall rejected the command: {detail}"
    return None


class PyPowerwallCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch live data from the pypowerwall proxy.

    The returned dict has these keys: "aggregates", "soe", "grid_status",
    "time_remaining" and "strings". Only aggregates is required; the others are
    None if just that endpoint failed. "time_remaining" is a float in hours, and
    "strings" is only fetched when the "Show strings" option is on.
    """

    config_entry: PowerwallDashboardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerwallDashboardConfigEntry,
        url: str,
        scan_interval: int,
        show_strings: bool,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} pypowerwall",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._url = url
        self._show_strings = show_strings

    async def _fetch(self, path: str) -> Any:
        """GET a pypowerwall endpoint and return its parsed JSON."""
        session = async_get_clientsession(self.hass)
        async with session.get(
            f"{self._url}{path}", timeout=POWERWALL_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _fetch_optional(self, path: str) -> Any:
        """Like _fetch, but return None instead of failing the whole update."""
        try:
            return await self._fetch(path)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Optional pypowerwall endpoint %s failed: %s", path, err)
            return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch every endpoint concurrently."""
        requests = [
            self._fetch(PYPOWERWALL_AGGREGATES_PATH),
            self._fetch_optional(PYPOWERWALL_SOE_PATH),
            self._fetch_optional(PYPOWERWALL_GRID_STATUS_PATH),
            self._fetch_optional(PYPOWERWALL_TIME_REMAINING_PATH),
        ]
        if self._show_strings:
            requests.append(self._fetch_optional(PYPOWERWALL_STRINGS_PATH))

        try:
            aggregates, soe, grid_status, time_remaining, *extra = (
                await asyncio.gather(*requests)
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error talking to pypowerwall: {err}") from err

        return {
            "aggregates": aggregates,
            "soe": soe,
            "grid_status": grid_status,
            "time_remaining": _parse_time_remaining(time_remaining),
            "strings": extra[0] if extra else None,
        }


class UpdateStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the gateway's firmware update status from the pypowerwall proxy.

    The returned dict is the parsed JSON of /api/system/update/status, e.g.
    {"state": "/update_succeeded", "version": "26.34.3 f2e0e391", ...}.
    """

    config_entry: PowerwallDashboardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerwallDashboardConfigEntry,
        url: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} update status",
            update_interval=timedelta(seconds=SCAN_INTERVAL_UPDATE),
        )
        self._url = url

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the update status."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self._url}{PYPOWERWALL_UPDATE_STATUS_PATH}",
                timeout=POWERWALL_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error fetching update status: {err}") from err

        if not isinstance(payload, dict):
            raise UpdateFailed(f"Unexpected update status response: {payload!r}")
        return payload


class ControlCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read the Powerwall's control settings and send control commands.

    Only created when the "Allow controls" option is on. The data dict has the
    keys "is_connected", "reserve", "mode", "grid_charging", "grid_export" and
    "max_backup" (the parsed /control/max_backup response), each None if just
    that endpoint failed. Reads need no token; commands use the control secret.
    """

    config_entry: PowerwallDashboardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerwallDashboardConfigEntry,
        url: str,
        secret: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} controls",
            update_interval=timedelta(seconds=SCAN_INTERVAL_CONTROL),
        )
        self._url = url
        self._secret = secret
        # How long "Max backup" runs when switched on. It has no endpoint to read
        # back, so the duration number entity sets it here.
        self.max_backup_minutes: float = DEFAULT_MAX_BACKUP_MINUTES

    # -- Reading -------------------------------------------------------
    async def _fetch_optional(self, path: str) -> Any:
        """GET a control endpoint; None if it fails."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self._url}{path}", timeout=POWERWALL_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Control endpoint %s failed: %s", path, err)
            return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Read every control setting concurrently."""
        data = _build_control_data(
            *await asyncio.gather(
                self._fetch_optional(PYPOWERWALL_IS_CONNECTED_PATH),
                self._fetch_optional(PYPOWERWALL_GET_RESERVE_PATH),
                self._fetch_optional(PYPOWERWALL_GET_MODE_PATH),
                self._fetch_optional(CONTROL_GRID_CHARGING_PATH),
                self._fetch_optional(CONTROL_GRID_EXPORT_PATH),
                self._fetch_optional(CONTROL_MAX_BACKUP_PATH),
            )
        )
        if all(value is None for value in data.values()):
            raise UpdateFailed("Could not read any control settings from pypowerwall")
        return data

    # -- Writing -------------------------------------------------------
    def _apply(self, **changes: Any) -> None:
        """Show a just-sent change right away; the next poll confirms it."""
        self.async_set_updated_data({**(self.data or {}), **changes})

    async def _async_post(
        self,
        path: str,
        *,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """POST a control command, raising HomeAssistantError if it fails."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"{self._url}{path}",
                data=data,
                json=json_body,
                headers=headers,
                timeout=CONTROL_TIMEOUT,
            ) as resp:
                status = resp.status
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Could not reach pypowerwall: {err}") from err

        try:
            payload = json.loads(text)
        except ValueError:
            payload = None

        if (message := _control_error(status, payload, text)) is not None:
            raise HomeAssistantError(message)

    async def _async_post_form(self, path: str, value: str) -> None:
        """POST a proxy-style form-encoded command carrying the control secret."""
        await self._async_post(
            path,
            data={
                "value": value,
                "token": self._secret,
                "mode": "",
                "level": "",
                "power_watts": "",
                "duration_seconds": "",
            },
        )

    async def async_set_grid_connected(self, connected: bool) -> None:
        """Reconnect to the grid, or go off-grid (island the house).

        Islanding takes a JSON body and the token in the Authorization header.
        The server locks islanding for a minute after any request.
        """
        body: dict[str, Any] = (
            {"value": "on_grid"}
            if connected
            else {"value": "off_grid", "confirm": True}
        )
        await self._async_post(
            CONTROL_ISLANDING_PATH,
            json_body=body,
            headers={"Authorization": f"Bearer {self._secret}"},
        )
        self._apply(is_connected=connected)

    async def async_set_reserve(self, percent: float) -> None:
        """Set the backup reserve (0-100 %)."""
        value = int(round(percent))
        await self._async_post_form(CONTROL_RESERVE_PATH, str(value))
        self._apply(reserve=float(value))

    async def async_set_mode(self, mode: str) -> None:
        """Set the operating mode (self_consumption, autonomous or backup)."""
        await self._async_post_form(CONTROL_MODE_PATH, mode)
        self._apply(mode=mode)

    async def async_set_grid_charging(self, enabled: bool) -> None:
        """Allow or forbid charging the battery from the grid."""
        await self._async_post_form(
            CONTROL_GRID_CHARGING_PATH, "true" if enabled else "false"
        )
        self._apply(grid_charging=enabled)

    async def async_set_grid_export(self, value: str) -> None:
        """Set the grid export rule (battery_ok, pv_only or never)."""
        await self._async_post_form(CONTROL_GRID_EXPORT_PATH, value)
        self._apply(grid_export=value)

    async def async_start_max_backup(self, minutes: float) -> None:
        """Start a manual max backup event lasting the given number of minutes."""
        seconds = max(MAX_BACKUP_MIN_SECONDS, round(minutes * 60))
        await self._async_post_form(CONTROL_MAX_BACKUP_PATH, str(seconds))

        now = int(time.time())
        current = (self.data or {}).get("max_backup") or {}
        self._apply(
            max_backup={
                **current,
                "manual_backup": {
                    "start_time": now,
                    "duration_seconds": seconds,
                    "end_time": now + seconds,
                    "active": True,
                },
            }
        )

    async def async_cancel_max_backup(self) -> None:
        """Cancel the current manual max backup event."""
        await self._async_post_form(CONTROL_MAX_BACKUP_PATH, "cancel")

        current = (self.data or {}).get("max_backup") or {}
        manual = current.get("manual_backup")
        self._apply(
            max_backup={
                **current,
                "manual_backup": {**manual, "active": False}
                if isinstance(manual, dict)
                else {"active": False},
            }
        )


class InfluxDbCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Fetch today's energy totals (kWh) from InfluxDB in a single query.

    The returned dict maps each key in ENERGY_FIELDS to its total so far today.
    """

    config_entry: PowerwallDashboardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerwallDashboardConfigEntry,
        url: str,
        timezone: str,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} influxdb",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._url = url
        self._timezone = timezone

    async def _start_of_day_utc(self) -> str:
        """Return midnight today, in the configured timezone, as a UTC timestamp."""
        tz = await dt_util.async_get_time_zone(self._timezone)
        if tz is None:
            raise UpdateFailed(f"Unknown timezone: {self._timezone}")
        midnight = dt_util.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return dt_util.as_utc(midnight).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _build_query(self, start: str) -> str:
        """Build one InfluxQL query that integrates every energy field.

        integral() returns value-seconds, so dividing by 1000 gives kW-seconds
        and by 3600 gives kWh.
        """
        selects = ", ".join(
            f'integral("{field}") / 1000 / 3600 AS "{key}"'
            for key, field in ENERGY_FIELDS.items()
        )
        return (
            f"SELECT {selects} "
            f'FROM "{INFLUXDB_RETENTION_POLICY}"."{INFLUXDB_MEASUREMENT}" '
            f"WHERE time >= '{start}' AND time <= now()"
        )

    async def _async_update_data(self) -> dict[str, float]:
        """Run the query and parse the result."""
        start = await self._start_of_day_utc()
        session = async_get_clientsession(self.hass)

        try:
            async with session.get(
                f"{self._url}/query",
                params={"db": INFLUXDB_DATABASE, "q": self._build_query(start)},
                timeout=INFLUXDB_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error talking to InfluxDB: {err}") from err

        return self._parse(payload)

    @staticmethod
    def _parse(payload: dict[str, Any]) -> dict[str, float]:
        """Turn an InfluxDB v1 /query response into {sensor_key: kWh}.

        Response shape: {"results": [{"series": [{"columns": [...],
        "values": [[time, v1, v2, ...]]}]}]}. Columns are matched by name
        rather than position.
        """
        if "error" in payload:
            raise UpdateFailed(f"InfluxDB error: {payload['error']}")

        try:
            results = payload.get("results") or [{}]
            if "error" in results[0]:
                raise UpdateFailed(f"InfluxDB query error: {results[0]['error']}")

            series = results[0].get("series")
            if not series:
                # No data points yet today (e.g. just after midnight): report 0.
                return {key: 0.0 for key in ENERGY_FIELDS}

            row = dict(zip(series[0]["columns"], series[0]["values"][0], strict=False))
            # A column can be null if that field has no data; treat it as 0.
            return {key: float(row.get(key) or 0) for key in ENERGY_FIELDS}
        except (KeyError, IndexError, TypeError, ValueError) as err:
            raise UpdateFailed(f"Unexpected InfluxDB response: {err}") from err
