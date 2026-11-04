"""
Shared utilities for CV-CUE MCP tools.

Every tool returns an envelope via ok() / err() so the LLM always gets the
same {ok, data, message} structure (same contract as the RUCKUS One MCP).
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import CvcueClient

# Keys CV-CUE uses for the record list inside paged responses
_LIST_KEYS = (
    "managedDevices", "clientList", "eventList", "apList", "switches", "wiredClientList",
    "clientEvents", "deviceLogs", "radios", "samples",
    "data", "list", "content", "items", "results",
)


# ---------------------------------------------------------------------------
# Secret redaction — CV-CUE returns PSK passphrases, RADIUS secrets, etc. in
# plain text. They are masked before reaching the LLM unless the operator sets
# CVCUE_REDACT_SECRETS=false.
# ---------------------------------------------------------------------------

REDACTED = "***REDACTED***"
REDACT_SECRETS = True
_SECRET_KEY_PARTS = (
    "passphrase", "password", "secret", "keyvalue", "privatekey", "presharedkey", "wpakey", "grekey",
)


def is_secret_key(key: str) -> bool:
    k = key.lower().replace("_", "")
    return any(part in k for part in _SECRET_KEY_PARTS)


def redact(data: Any) -> Any:
    """Recursively replace non-empty string values of secret-looking keys."""
    if isinstance(data, dict):
        return {
            k: REDACTED if isinstance(v, str) and v and is_secret_key(str(k)) else redact(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


def ok(data: Any, message: str = "") -> dict[str, Any]:
    return {"ok": True, "data": redact(data) if REDACT_SECRETS else data, "message": message}


def err(message: str, status: int = 0) -> dict[str, Any]:
    return {"ok": False, "data": None, "message": message, "status": status}


def safe(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
    """Turn any exception raised by a tool into an err() envelope."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced to the LLM
            return err(f"{type(exc).__name__}: {exc}", getattr(exc, "status", 0))

    return wrapper


def writes_disabled() -> dict[str, Any]:
    return err(
        "Write operations are disabled for this connection. Local server: set CVCUE_ENABLE_WRITES=true "
        "in its environment (or .env). Hosted server: send the header 'X-CVCUE-Enable-Writes: true' "
        "(only honoured if the operator allows writes)."
    )


# ---------------------------------------------------------------------------
# Paged responses
# ---------------------------------------------------------------------------

def rows_of(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in _LIST_KEYS:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def total_of(data: Any, default: int) -> int:
    if isinstance(data, dict) and isinstance(data.get("totalCount"), int):
        return data["totalCount"]
    return default


def page_params(start: int = 0, size: int = 50, total: bool = True) -> dict[str, Any]:
    """CV-CUE paging: startindex is a 0-based record offset."""
    return {"startindex": start, "pagesize": size, "totalcountrequired": total}


async def fetch_all(
    client: CvcueClient,
    path: str,
    params: dict[str, Any] | None = None,
    page_size: int = 500,
    max_items: int = 10000,
) -> tuple[list[Any], int]:
    """Walk startindex/pagesize pages and return (rows, totalCount)."""
    rows: list[Any] = []
    total = 0
    start = 0
    session_id = None
    while True:
        q = {**(params or {}), **page_params(start, page_size, True)}
        if session_id:
            q["pagingSessionId"] = session_id
        data = await client.get(path, params=q)
        batch = rows_of(data)
        total = total_of(data, len(rows) + len(batch))
        if isinstance(data, dict) and data.get("pagingSessionId"):
            session_id = data["pagingSessionId"]
        rows.extend(batch)
        if not batch or len(rows) >= total or len(rows) >= max_items or len(batch) < page_size:
            return rows[:max_items], total
        start += len(batch)


# ---------------------------------------------------------------------------
# Time helpers — CV-CUE expects epoch milliseconds. (Some spec descriptions say
# microseconds; the live server rejects µs values with START_TIME_GREATER_THAN_CURRENT_TIME.)
# ---------------------------------------------------------------------------

def now_ms() -> int:
    return int(time.time() * 1000)


def hours_ago_ms(hours: float) -> int:
    return now_ms() - int(hours * 3_600_000)


def iso(ts: Any) -> Any:
    """Render an epoch ms/µs timestamp as ISO-8601 UTC (passthrough otherwise)."""
    if not isinstance(ts, (int, float)) or ts <= 0:
        return ts
    if ts > 1e14:          # microseconds
        ts = ts / 1000
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000))


# ---------------------------------------------------------------------------
# Record shaping
# ---------------------------------------------------------------------------

def pick(record: Any, fields: tuple[str, ...]) -> Any:
    if not isinstance(record, dict):
        return record
    return {f: record[f] for f in fields if f in record and record[f] not in (None, "", [])}


def counts(rows: list[dict], key: str | Callable[[dict], Any], top: int = 15) -> dict[str, int]:
    getter = key if callable(key) else (lambda r: r.get(key))
    c = Counter(str(getter(r)) for r in rows if getter(r) not in (None, ""))
    return dict(c.most_common(top))


def norm_mac(mac: str) -> str:
    """Normalise a MAC to CV-CUE's upper-case colon form."""
    hexes = "".join(ch for ch in mac if ch.isalnum()).upper()
    if len(hexes) != 12:
        return mac.strip().upper()
    return ":".join(hexes[i:i + 2] for i in range(0, 12, 2))
