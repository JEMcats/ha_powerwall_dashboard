"""Per-Powerwall diagnostic data: parsing only, no Home Assistant imports.

pypowerwall numbers the Powerwalls PW1, PW2, ... in the same order in every
endpoint, with the leader first, so that numbering is used as the identity:

* /pod         PW1_name, PW1_POD_nom_full_pack_energy (Wh),
               PW1_POD_nom_energy_remaining (Wh), PW2_name, ...
* /temps/pw    PW1_temp, PW2_temp, ... in Celsius (None for no reading)
* /fans/pw     FAN1_actual (rpm), FAN1_duty (%), FAN2_actual, ... (Powerwall 3
               only: two fans per unit, so PW1 owns FAN1-2, PW2 owns FAN3-4)
"""

from __future__ import annotations

import re
from typing import Any

from .const import DEFAULT_POWERWALL_SPEC_KWH, FANS_PER_POWERWALL, POWERWALL_MODELS

_POD_NAME = re.compile(r"^PW(\d+)_name$")
_TEMP = re.compile(r"^PW(\d+)_temp$")
_FAN = re.compile(r"^FAN(\d+)_actual$")


def _number(value: Any) -> float | None:
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


def powerwall_model(name: Any) -> tuple[str | None, float]:
    """Return (model name, published capacity in kWh) for a /pod device name.

    Names look like "TEPOD--1707000-30-L--TG126034..." (type, part number,
    serial). Unknown part numbers return (None, the default capacity).
    """
    if isinstance(name, str):
        parts = name.split("--")
        if len(parts) > 1:
            prefix = parts[1].split("-")[0]
            if prefix in POWERWALL_MODELS:
                return POWERWALL_MODELS[prefix]
    return None, DEFAULT_POWERWALL_SPEC_KWH


def deviation_percent(capacity_kwh: float | None, spec_kwh: float | None) -> float | None:
    """Percent difference from spec: negative means below the published capacity."""
    if capacity_kwh is None or not spec_kwh:
        return None
    return (capacity_kwh - spec_kwh) / spec_kwh * 100


def build_diagnostics(pod: Any, temps: Any, fans: Any) -> dict[str, Any]:
    """Combine /pod, /temps/pw and /fans/pw into per-Powerwall and combined data.

    Any argument may be None or empty (that endpoint failed or has no data).
    Returns {"powerwalls": {1: {...}, 2: {...}}, "combined": {...}}.
    """
    pod = pod if isinstance(pod, dict) else {}
    temps = temps if isinstance(temps, dict) else {}
    fans = fans if isinstance(fans, dict) else {}

    # Discover the Powerwalls from whichever endpoints know about them.
    indexes: set[int] = set()
    for key in pod:
        if match := _POD_NAME.match(key):
            indexes.add(int(match[1]))
    for key in temps:
        if match := _TEMP.match(key):
            indexes.add(int(match[1]))
    for key in fans:
        if match := _FAN.match(key):
            indexes.add((int(match[1]) - 1) // FANS_PER_POWERWALL + 1)

    powerwalls: dict[int, dict[str, Any]] = {}
    for index in sorted(indexes):
        name = pod.get(f"PW{index}_name")
        model, spec_kwh = powerwall_model(name)

        # The gateway reports Wh. A zero means "no reading", not an empty pack.
        capacity_wh = _number(pod.get(f"PW{index}_POD_nom_full_pack_energy"))
        charge_wh = _number(pod.get(f"PW{index}_POD_nom_energy_remaining"))
        capacity = capacity_wh / 1000 if capacity_wh and capacity_wh > 0 else None
        charge = charge_wh / 1000 if charge_wh is not None else None

        first_fan = (index - 1) * FANS_PER_POWERWALL + 1
        fan_list: list[dict[str, Any]] = []
        for slot in range(FANS_PER_POWERWALL):
            number = first_fan + slot
            if f"FAN{number}_actual" in fans or f"FAN{number}_duty" in fans:
                fan_list.append(
                    {
                        "slot": slot + 1,
                        "rpm": _number(fans.get(f"FAN{number}_actual")),
                        "duty": _number(fans.get(f"FAN{number}_duty")),
                    }
                )
        rpms = [fan["rpm"] for fan in fan_list if fan["rpm"] is not None]

        powerwalls[index] = {
            "name": name if isinstance(name, str) else None,
            "model": model,
            "spec_kwh": spec_kwh,
            "has_pod": f"PW{index}_name" in pod,
            "has_temperature": f"PW{index}_temp" in temps,
            "has_fans": bool(fan_list),
            "capacity_kwh": capacity,
            "charge_kwh": charge,
            "deviation_percent": deviation_percent(capacity, spec_kwh),
            "difference_kwh": capacity - spec_kwh if capacity is not None else None,
            "temperature_c": _number(temps.get(f"PW{index}_temp")),
            "fan_rpm": sum(rpms) / len(rpms) if rpms else None,
            "fans": fan_list,
        }

    # Combined totals across every Powerwall that reports pod data. The spec is
    # summed over the same units that have a capacity, so the comparison is fair.
    pods = [unit for unit in powerwalls.values() if unit["has_pod"]]
    with_capacity = [unit for unit in pods if unit["capacity_kwh"] is not None]
    charges = [unit["charge_kwh"] for unit in pods if unit["charge_kwh"] is not None]

    capacity_total = (
        sum(unit["capacity_kwh"] for unit in with_capacity) if with_capacity else None
    )
    spec_total = (
        sum(unit["spec_kwh"] for unit in with_capacity) if with_capacity else None
    )
    combined = {
        "count": len(pods),
        "capacity_kwh": capacity_total,
        "charge_kwh": sum(charges) if charges else None,
        "spec_kwh": spec_total,
        "deviation_percent": deviation_percent(capacity_total, spec_total),
        "difference_kwh": (
            capacity_total - spec_total if capacity_total is not None else None
        ),
    }

    return {"powerwalls": powerwalls, "combined": combined}
