"""Writability table and the one write gate.

Everything that is not in ``WRITABLE`` is read-only: unknown or manufacturer clusters
(0x117CFC01, any id > 0xFFFF or >= 0xFC00), lists and structs (presets, schedules), global
attributes (>= 0xFFF8) and every cluster not named below. Entries were checked against the
Matter Application Cluster Specification (1.4) attribute tables (access column RW) and the
enums in the CHIP cluster objects. Anything not certain is left out on purpose, e.g. Power
Source (47): its only writable attribute (Order) is not confirmed, so the cluster has no entry.

``async_write`` is the only place in this integration that calls ``write_attribute``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .client import MatterClientUnavailable, find_node, get_matter_client
from .const import STORE_KEY
from .errors import (
    CLIENT_ERRORS,
    DEVICE_TIMEOUT,
    error_text,
    log_failure,
    record_activity,
    run_device_call,
)
from .metadata import friendly_labels, parse_path

_LOGGER = logging.getLogger(__name__)

READBACK_TIMEOUT = 10.0  # seconds

ENUM = "enum"
INT = "int"
BOOL = "bool"


@dataclass(frozen=True)
class WritableAttr:
    """One writable attribute: type plus allowed values or range."""

    name: str
    type: str  # enum | int | bool
    values: dict[int, str] | None = None  # enum: allowed value -> label
    min: int | None = None  # int: fixed range
    max: int | None = None
    # int: range from the node's own attributes (first pair present wins), same endpoint
    limit_attrs: tuple[tuple[int, int], ...] = ()
    unit: str | None = None  # "°C" for raw 0.01 °C values


_CELSIUS = "°C"
_HEAT = ((21, 22), (3, 4))
_COOL = ((23, 24), (5, 6))

# (cluster id, attribute id) -> definition
# fmt: off
WRITABLE: dict[tuple[int, int], WritableAttr] = {
    # Identify (3), spec "Identify Cluster": IdentifyTime uint16, RW
    (3, 0): WritableAttr("IdentifyTime", INT, min=0, max=0xFFFF),
    # Time Format Localization (44), spec "Time Format Localization Cluster": HourFormat RW
    (44, 0): WritableAttr(
        "HourFormat", ENUM, values={0: "12hr", 1: "24hr", 255: "UseActiveLocale"}
    ),
    # ActiveCalendarType RW (must also be one of SupportedCalendarTypes; the device checks that)
    (44, 1): WritableAttr(
        "ActiveCalendarType",
        ENUM,
        values={
            0: "Buddhist", 1: "Chinese", 2: "Coptic", 3: "Ethiopian", 4: "Gregorian", 5: "Hebrew",
            6: "Indian", 7: "Islamic", 8: "Japanese", 9: "Korean", 10: "Persian", 11: "Taiwanese",
            255: "UseActiveLocale",
        },
    ),
    # Unit Localization (45), spec "Unit Localization Cluster": TemperatureUnit RW
    (45, 0): WritableAttr(
        "TemperatureUnit", ENUM, values={0: "Fahrenheit", 1: "Celsius", 2: "Kelvin"}
    ),
    # Thermostat (513), spec "Thermostat Cluster" attribute table (RW rows)
    # LocalTemperatureCalibration int8, -2.5 .. 2.5 °C in 0.1 °C steps
    (513, 16): WritableAttr("LocalTemperatureCalibration", INT, min=-25, max=25),
    # Occupied/Unoccupied setpoints int16 in 0.01 °C, within the node's own limits:
    # heating Min/MaxHeatSetpointLimit (21/22) else AbsMin/AbsMaxHeatSetpointLimit (3/4);
    # cooling Min/MaxCoolSetpointLimit (23/24) else AbsMin/AbsMaxCoolSetpointLimit (5/6)
    (513, 17): WritableAttr("OccupiedCoolingSetpoint", INT, limit_attrs=_COOL, unit=_CELSIUS),
    (513, 18): WritableAttr("OccupiedHeatingSetpoint", INT, limit_attrs=_HEAT, unit=_CELSIUS),
    (513, 19): WritableAttr("UnoccupiedCoolingSetpoint", INT, limit_attrs=_COOL, unit=_CELSIUS),
    (513, 20): WritableAttr("UnoccupiedHeatingSetpoint", INT, limit_attrs=_HEAT, unit=_CELSIUS),
    # ControlSequenceOfOperation enum 0-5
    (513, 27): WritableAttr(
        "ControlSequenceOfOperation",
        ENUM,
        values={
            0: "CoolingOnly", 1: "CoolingWithReheat", 2: "HeatingOnly", 3: "HeatingWithReheat",
            4: "CoolingAndHeating", 5: "CoolingAndHeatingWithReheat",
        },
    ),
    # SystemMode enum (2 is reserved)
    (513, 28): WritableAttr(
        "SystemMode",
        ENUM,
        values={
            0: "Off", 1: "Auto", 3: "Cool", 4: "Heat", 5: "EmergencyHeat", 6: "Precooling",
            7: "FanOnly", 8: "Dry", 9: "Sleep",
        },
    ),
    # Thermostat User Interface Configuration (516), spec "Thermostat User Interface Configuration"
    (516, 0): WritableAttr(
        "TemperatureDisplayMode", ENUM, values={0: "Celsius", 1: "Fahrenheit"}
    ),
    (516, 1): WritableAttr(
        "KeypadLockout",
        ENUM,
        values={0: "NoLockout", 1: "Lockout1", 2: "Lockout2", 3: "Lockout3", 4: "Lockout4",
                5: "Lockout5"},
    ),
    (516, 2): WritableAttr(
        "ScheduleProgrammingVisibility",
        ENUM,
        values={0: "ScheduleProgrammingPermitted", 1: "ScheduleProgrammingDenied"},
    ),
}
# fmt: on


class WriteRefused(HomeAssistantError):
    """The gate refused the write (nothing was sent to the device)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def writable_spec(cluster: int, attribute: int) -> WritableAttr | None:
    """The table entry, or None. Manufacturer clusters and globals never match."""
    if cluster > 0xFFFF or cluster >= 0xFC00 or attribute >= 0xFFF8:
        return None
    return WRITABLE.get((cluster, attribute))


def resolve_limits(
    spec: WritableAttr, attributes: dict[str, Any], endpoint: int, cluster: int
) -> tuple[int | None, int | None]:
    """Allowed (min, max) of an int attribute for this node."""
    if spec.limit_attrs:
        for lo_id, hi_id in spec.limit_attrs:
            lo = attributes.get(f"{endpoint}/{cluster}/{lo_id}")
            hi = attributes.get(f"{endpoint}/{cluster}/{hi_id}")
            if _is_int(lo) and _is_int(hi):
                return lo, hi
        return None, None
    return spec.min, spec.max


def describe_write(
    attributes: dict[str, Any], endpoint: int, cluster: int, attribute: int
) -> dict[str, Any] | None:
    """What the panel needs to edit this attribute, or None when it is read-only."""
    spec = writable_spec(cluster, attribute)
    if spec is None:
        return None
    lo, hi = resolve_limits(spec, attributes, endpoint, cluster)
    if spec.type == INT and (lo is None or hi is None):
        return None  # limits unknown: not editable
    out: dict[str, Any] = {"type": spec.type, "min": lo, "max": hi, "unit": spec.unit}
    if spec.values is not None:
        out["values"] = {str(k): v for k, v in spec.values.items()}
        labels = friendly_labels(cluster, attribute)
        if labels:
            out["labels"] = {str(k): v for k, v in labels.items() if k in spec.values}
    return out


def validate_value(spec: WritableAttr, value: Any, lo: int | None, hi: int | None) -> None:
    """Raise WriteRefused unless value is allowed for this attribute."""
    if spec.type == BOOL:
        if not isinstance(value, bool):
            raise WriteRefused("invalid_value", f"{spec.name} needs a boolean")
        return
    if not _is_int(value):
        raise WriteRefused("invalid_value", f"{spec.name} needs an integer")
    if spec.type == ENUM:
        if spec.values is None or value not in spec.values:
            raise WriteRefused("invalid_value", f"{value} is not a valid {spec.name} value")
        return
    if lo is None or hi is None:
        raise WriteRefused("invalid_value", f"No known limits for {spec.name}")
    if not lo <= value <= hi:
        raise WriteRefused("invalid_value", f"{value} is outside {lo}..{hi} for {spec.name}")


def check_write(node: Any, path: str, value: Any) -> WritableAttr:
    """All checks that need no I/O. Raises WriteRefused."""
    try:
        endpoint, cluster, attribute = parse_path(path)
    except ValueError as err:
        raise WriteRefused("invalid_path", f"Bad attribute path {path!r}") from err
    spec = writable_spec(cluster, attribute)
    if spec is None:
        raise WriteRefused("not_writable", f"{path} is read-only")
    attributes = node.node_data.attributes
    if path not in attributes:
        raise WriteRefused("not_found", f"{path} does not exist on node {node.node_id}")
    if not node.available:
        raise WriteRefused("node_unavailable", f"Node {node.node_id} is unavailable")
    lo, hi = resolve_limits(spec, attributes, endpoint, cluster)
    validate_value(spec, value, lo, hi)
    return spec


async def _read_back(client: Any, node: Any, node_id: int, path: str) -> tuple[bool, Any]:
    """(got_value, value) after a write; (False, None) on timeout."""
    try:
        async with asyncio.timeout(READBACK_TIMEOUT):
            if hasattr(client, "read_attribute"):
                result = await client.read_attribute(node_id, path)
                if isinstance(result, dict):
                    if path in result:
                        return True, result[path]
                    if len(result) == 1:
                        return True, next(iter(result.values()))
                elif result is not None:
                    return True, result
            # No usable read_attribute: wait for the update event, else the cached value
            return await _wait_update(client, node, node_id, path)
    except TimeoutError:
        return False, None
    except CLIENT_ERRORS as err:  # the write went through; only the read-back failed
        _LOGGER.warning("Matter read-back node=%s path=%s failed: %s", node_id, path, err)
        return False, None


async def _wait_update(client: Any, node: Any, node_id: int, path: str) -> tuple[bool, Any]:
    from matter_server.common.models import EventType

    fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

    def on_update(_event: Any, data: Any) -> None:
        if not fut.done():
            fut.set_result(data)

    unsub = client.subscribe_events(
        on_update, EventType.ATTRIBUTE_UPDATED, node_filter=node_id, attr_path_filter=path
    )
    try:
        return True, await fut
    finally:
        unsub()


def _write_failed(result: Any) -> str | None:
    """Error text when the write response carries a non-zero status, else None."""
    items = result if isinstance(result, list) else [result]
    for item in items:
        if isinstance(item, dict):
            status = item.get("Status", item.get("status"))
            if isinstance(status, int) and status != 0:
                return f"Device refused the write (status {status})"
    return None


async def async_write(hass: HomeAssistant, node_id: int, path: str, value: Any) -> dict[str, Any]:
    """The write gate: check, write, read back. Returns {ok, written, read_back, matches}."""
    client = get_matter_client(hass)
    node = _require_node(client, node_id)
    check_write(node, path, value)
    old = _current_value(hass, node, path)
    _LOGGER.info("Matter write node=%s path=%s old=%r new=%r", node_id, path, old, value)
    # A late ATTRIBUTE_UPDATED after a timeout still reaches the live store and the entities
    # (their subscriptions do not depend on this call), so the value catches up on its own.
    what = f"write node={node_id} path={path}"
    result = await run_device_call(
        hass, _LOGGER, "write", what, "Write", client.write_attribute(node_id, path, value),
        WriteRefused, device_timeout=DEVICE_TIMEOUT, node_id=node_id, path=path, value=value,
    )  # fmt: skip
    if (problem := _write_failed(result)) is not None:
        log_failure(
            hass, _LOGGER, "write", what, "write_failed", problem,
            node_id=node_id, path=path, value=value,
        )  # fmt: skip
        raise WriteRefused("write_failed", problem)
    got, read_back = await _read_back(client, node, node_id, path)
    matches = got and read_back == value
    _LOGGER.info(
        "Matter write node=%s path=%s read back %s%r matches=%s",
        node_id, path, "" if got else "(timeout) ", read_back, matches,
    )  # fmt: skip
    record_activity(
        hass, "write", node_id=node_id, path=path, value=value, ok=True,
        read_back=read_back if got else None, matches=bool(matches), timeout=not got,
    )  # fmt: skip
    return {
        "ok": True,
        "written": value,
        "read_back": read_back,
        "matches": matches,
        "timeout": not got,
    }


BATCH_ERRORS: tuple[type[Exception], ...] = (MatterClientUnavailable, *CLIENT_ERRORS)
WRITE_SPACING = 0.5  # seconds between two writes of a batch (Thread networks dislike bursts)
MAX_BATCH = 50

_SKIP_REASONS = {
    "node_not_found": "node not found",
    "node_unavailable": "unavailable",
    "not_writable": "not writable",
    "not_found": "attribute missing",
    "invalid_path": "bad path",
    "invalid_value": "out of range",
}


def _current_value(hass: HomeAssistant, node: Any, path: str) -> Any:
    """Newest known raw value: the live overlay (snapshots go stale), else the snapshot."""
    store = hass.data.get(STORE_KEY)
    if store is not None:
        overlay = store.overlay(node.node_id)
        if path in overlay:
            return overlay[path]
    return node.node_data.attributes.get(path)


async def _pause() -> None:
    await asyncio.sleep(WRITE_SPACING)


def _item_result(node_id: int, path: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"node_id": node_id, "path": path, "status": status, **extra}


def _require_node(client: Any, node_id: int) -> Any:
    node = find_node(client, node_id)
    if node is None:
        raise WriteRefused("node_not_found", f"Node {node_id} does not exist")
    return node


def _safe_old(hass: HomeAssistant, client: Any, node_id: int, path: str) -> Any:
    node = find_node(client, node_id)
    return None if node is None else _current_value(hass, node, path)


async def async_write_many(
    hass: HomeAssistant,
    items: list[dict[str, Any]],
    value: Any,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Write one value to many attributes, one after the other; one failure never stops the batch.

    Every real write goes through async_write. Rows that cannot be written (unavailable, not
    writable, value refused by this node's limits) are skipped without touching the client, rows
    already at the value are reported as no_change. Status: ok | mismatch | timeout | error |
    skipped | no_change.
    """
    client = get_matter_client(hass)
    results: list[dict[str, Any]] = []
    wrote = False
    total = len(items)
    for item in items:
        node_id, path = item["node_id"], item["path"]
        result: dict[str, Any]
        try:
            node = _require_node(client, node_id)
            check_write(node, path, value)
            old = _current_value(hass, node, path)
            if old == value:
                result = _item_result(node_id, path, "no_change", old=old, read_back=old)
            else:
                if wrote:
                    await _pause()
                wrote = True
                out = await async_write(hass, node_id, path, value)
                status = "timeout" if out["timeout"] else "ok" if out["matches"] else "mismatch"
                result = _item_result(
                    node_id, path, status, old=old, read_back=out["read_back"],
                    matches=out["matches"], timeout=out["timeout"],
                )  # fmt: skip
        except WriteRefused as err:
            if err.code == "timeout":
                result = _item_result(
                    node_id, path, "timeout", code=err.code, error=str(err),
                    old=_safe_old(hass, client, node_id, path), read_back=None,
                    matches=False, timeout=True,
                )  # fmt: skip
            elif err.code == "write_failed":
                result = _item_result(node_id, path, "error", code=err.code, error=str(err))
            else:
                reason = _SKIP_REASONS.get(err.code, err.code)
                result = _item_result(
                    node_id, path, "skipped", code=err.code, reason=reason, error=str(err)
                )
        except BATCH_ERRORS as err:  # connection lost mid-batch
            _LOGGER.warning("Matter bulk write node=%s path=%s: %s", node_id, path, error_text(err))
            result = _item_result(node_id, path, "error", code="error", error=error_text(err))
        except Exception as err:  # outer edge of the batch: one bad row never stops the others
            _LOGGER.exception(
                "Matter bulk write node=%s path=%s failed unexpectedly", node_id, path
            )
            result = _item_result(node_id, path, "error", code="error", error=error_text(err))
        results.append(result)
        if progress is not None:
            progress(len(results), total, result)
    return results
