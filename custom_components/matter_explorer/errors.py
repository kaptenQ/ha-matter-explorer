"""Error classes of the matter client, a rate limiter for repeated warnings, and recent activity.

``CLIENT_ERRORS`` is what the MatterClient of matter-python-client 1.5.5 raises for a failed call:
``MatterError`` (errors the Matter Server reports: NodeNotExists, NodeNotReady, NodeNotResolving,
SDKStackError, InvalidArguments, ...), ``MatterClientException`` (transport: ConnectionClosed,
CannotConnect, ConnectionFailed, NotConnected, InvalidState, ...) and ``TimeoutError``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant
from matter_server.client.exceptions import MatterClientException
from matter_server.common.errors import MatterError

from .const import DOMAIN

CLIENT_ERRORS: tuple[type[Exception], ...] = (MatterError, MatterClientException, TimeoutError)

# How long a write or command to a device may take before we report "didn't answer". Thread
# devices that sleep (ICD / sleepy end devices) can take a while to wake up; 30 s is long enough
# for that and short enough for someone watching the panel.
DEVICE_TIMEOUT = 30.0  # seconds

ACTIVITY_KEY = f"{DOMAIN}_activity"
ACTIVITY_MAX = 20
LOG_INTERVAL = 300.0  # at most one identical warning per 5 minutes

_last_logged: dict[tuple[Any, ...], float] = {}


def log_limited(
    logger: logging.Logger,
    key: tuple[Any, ...],
    message: str,
    *args: Any,
    level: int = logging.WARNING,
) -> bool:
    """Log ``message`` unless the same ``key`` (e.g. (node_id, path)) was logged recently."""
    now = time.monotonic()
    last = _last_logged.get(key)
    if last is not None and now - last < LOG_INTERVAL:
        logger.debug("(repeated) " + message, *args)
        return False
    _last_logged[key] = now
    logger.log(level, message, *args)
    return True


def reset_log_limits() -> None:
    """Forget what was logged (tests, entry reload)."""
    _last_logged.clear()


def timeout_message(node_id: int) -> str:
    """The text shown when a device does not answer in time."""
    return f"Node {node_id} didn't answer within {DEVICE_TIMEOUT:g} s (asleep or out of reach?)"


def error_text(err: BaseException) -> str:
    """A readable message for a client error (the class name when it has no text)."""
    return str(err) or type(err).__name__


def record_activity(hass: HomeAssistant, kind: str, **fields: Any) -> None:
    """Keep the last ACTIVITY_MAX write / command results in memory, for diagnostics."""
    log = hass.data.setdefault(ACTIVITY_KEY, deque(maxlen=ACTIVITY_MAX))
    log.append({"time": time.time(), "kind": kind, **fields})


def log_failure(
    hass: HomeAssistant,
    logger: logging.Logger,
    kind: str,
    what: str,
    code: str,
    message: str,
    **fields: Any,
) -> None:
    """Log a failed write / command as a warning and keep it in the activity log."""
    logger.warning("Matter %s: %s", what, message)
    record_activity(hass, kind, ok=False, code=code, message=message, **fields)


async def run_device_call[T](
    hass: HomeAssistant,
    logger: logging.Logger,
    kind: str,
    what: str,
    name: str,
    call: Awaitable[T],
    refuse: Callable[[str, str], Exception],
    device_timeout: float = DEVICE_TIMEOUT,
    **fields: Any,
) -> T:
    """Await a call to a device with DEVICE_TIMEOUT; turn timeout / client errors into ``refuse``.

    Shared by the write gate and the command gate. ``what`` is the log label (``write node=1
    path=...``), ``name`` the text start of the user message ("Write" -> "Write failed: ..."),
    ``refuse(code, message)`` builds the gate's own exception, ``device_timeout`` is the gate's
    own module constant (so tests can shorten it), ``fields`` go to the activity log.
    """
    node_id = fields["node_id"]
    try:
        async with asyncio.timeout(device_timeout):
            return await call
    except TimeoutError as err:
        message = timeout_message(node_id)
        log_failure(hass, logger, kind, what, "timeout", message, **fields)
        raise refuse("timeout", message) from err
    except CLIENT_ERRORS as err:
        text = error_text(err)
        log_failure(hass, logger, kind, what, f"{kind}_failed", text, **fields)
        raise refuse(f"{kind}_failed", f"{name} failed: {text}") from err
