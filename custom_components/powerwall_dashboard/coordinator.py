"""Data update coordinators for the Powerwall Dashboard integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ENERGY_FIELDS,
    INFLUXDB_DATABASE,
    INFLUXDB_MEASUREMENT,
    INFLUXDB_RETENTION_POLICY,
    PYPOWERWALL_AGGREGATES_PATH,
    PYPOWERWALL_GRID_STATUS_PATH,
    PYPOWERWALL_SOE_PATH,
)

if TYPE_CHECKING:
    from . import PowerwallDashboardConfigEntry

_LOGGER = logging.getLogger(__name__)

POWERWALL_TIMEOUT = aiohttp.ClientTimeout(total=8)
# Integrating a full day of data can take a few seconds on a busy database.
INFLUXDB_TIMEOUT = aiohttp.ClientTimeout(total=30)


class PyPowerwallCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch live data from the pypowerwall proxy.

    The returned dict has three keys, each the parsed JSON of one endpoint:
    "aggregates", "soe" and "grid_status". The last two may be None if just
    that endpoint failed; the aggregates endpoint is required.
    """

    config_entry: PowerwallDashboardConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PowerwallDashboardConfigEntry,
        url: str,
        scan_interval: int,
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
        """Fetch all three endpoints concurrently."""
        try:
            aggregates, soe, grid_status = await asyncio.gather(
                self._fetch(PYPOWERWALL_AGGREGATES_PATH),
                self._fetch_optional(PYPOWERWALL_SOE_PATH),
                self._fetch_optional(PYPOWERWALL_GRID_STATUS_PATH),
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error talking to pypowerwall: {err}") from err

        return {"aggregates": aggregates, "soe": soe, "grid_status": grid_status}


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
