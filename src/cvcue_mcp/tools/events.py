"""Events (alerts) and WIPS / rogue AP tools."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import (
    counts,
    fetch_all,
    hours_ago_ms,
    iso,
    ok,
    page_params,
    pick,
    rows_of,
    safe,
    total_of,
)
from .locations import loc_id

EVENT_FIELDS = (
    "id", "eventSeverity", "category", "majorType", "intermediateType", "minorType",
    "summary", "startTime", "stopTime", "activityStatus", "readStatus", "vulnerable", "locationId",
)
DETECTED_AP_FIELDS = (
    "boxId", "name", "boxMacaddress", "group", "activeStatus", "active", "vendorName", "ssids",
    "bestSignalStrength", "numAssocClients", "banned", "suspicious", "misconfigured", "guest",
    "nonCompliant", "manuallyClassified", "locationId", "ipAddress",
)
AP_GROUPS = ("AUTHORIZED", "ROGUE", "EXTERNAL", "UNCATEGORIZED")


def shape_event(e: dict) -> dict:
    out = pick(e, EVENT_FIELDS)
    for k in ("startTime", "stopTime"):
        if k in out:
            out[k] = iso(out[k])
    if "locationId" in out:
        out["locationId"] = loc_id(out["locationId"])
    return out


def shape_detected_ap(a: dict) -> dict:
    out = pick(a, DETECTED_AP_FIELDS)
    if "locationId" in out:
        out["locationId"] = loc_id(out["locationId"])
    return out


async def recent_events(client: Any, location_id: int | None, hours: float, limit: int,
                        mac: list[str] | None = None) -> list[dict]:
    """Newest-first events within the last `hours`, up to `limit`."""
    cutoff = hours_ago_ms(hours)
    out: list[dict] = []
    start = 0
    while len(out) < limit:
        data = await client.get("/events", params={
            **page_params(start, 200, False), "locationid": location_id,
            "sortcolumn": "startTime", "sortascending": False, "macaddress": mac,
        })
        batch = rows_of(data)
        if not batch:
            break
        for e in batch:
            ts = e.get("startTime")
            if isinstance(ts, (int, float)) and ts > 1e14:
                ts = ts / 1000
            if isinstance(ts, (int, float)) and ts < cutoff:
                return out
            out.append(e)
        if len(batch) < 200:
            break
        start += len(batch)
    return out[:limit]


def register(mcp: FastMCP, get_client: Any) -> None:

    @mcp.tool()
    @safe
    async def cvcue_query_events(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        hours: Annotated[float, Field(description="Look-back window in hours (default 24)")] = 24,
        severity: Annotated[list[str] | None, Field(description="Keep only these severities (e.g. ['HIGH','MEDIUM'])")] = None,
        text: Annotated[str | None, Field(description="Case-insensitive substring match on the event summary")] = None,
        mac_address: Annotated[list[str] | None, Field(description="Events involving these device MACs")] = None,
        limit: Annotated[int, Field(description="Max events returned (default 100, max 1000)")] = 100,
    ) -> dict:
        """
        Recent CV-CUE events/alerts (WIPS, performance, connectivity, system),
        newest first, with severity, category, type, summary and timestamps.
        """
        rows = await recent_events(get_client(), location_id, hours, min(limit, 1000) * 3, mac_address)
        if severity:
            wanted = {s.upper() for s in severity}
            rows = [e for e in rows if str(e.get("eventSeverity", "")).upper() in wanted]
        if text:
            rows = [e for e in rows if text.lower() in str(e.get("summary", "")).lower()]
        rows = rows[: min(limit, 1000)]
        return ok({"hours": hours, "count": len(rows), "events": [shape_event(e) for e in rows]})

    @mcp.tool()
    @safe
    async def cvcue_event_summary(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        hours: Annotated[float, Field(description="Look-back window in hours (default 24)")] = 24,
    ) -> dict:
        """
        Summarize events in a time window: totals by severity, category and type,
        the most frequent summaries, and the latest high-severity events.
        """
        rows = await recent_events(get_client(), location_id, hours, 5000)
        high = [e for e in rows if str(e.get("eventSeverity", "")).upper() in ("HIGH", "CRITICAL")]
        return ok({
            "hours": hours,
            "total_events": len(rows),
            "truncated": len(rows) >= 5000,
            "by_severity": counts(rows, "eventSeverity"),
            "by_category": counts(rows, "category"),
            "by_type": counts(rows, "majorType"),
            "top_summaries": counts(rows, "summary", top=20),
            "unread": sum(1 for e in rows if e.get("readStatus") in (False, "UNREAD", 0)),
            "latest_high_severity": [shape_event(e) for e in high[:15]],
        })

    @mcp.tool()
    @safe
    async def cvcue_list_rogue_aps(
        group: Annotated[str, Field(description="Classification: ROGUE (default), EXTERNAL, UNCATEGORIZED, AUTHORIZED")] = "ROGUE",
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        active_only: Annotated[bool, Field(description="Only APs currently seen on the air")] = True,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 50,
    ) -> dict:
        """
        List APs detected by CV-CUE WIPS sensors by classification (rogue, external
        neighbor, uncategorized, authorized) with SSIDs, vendor, signal and clients.
        """
        params = {
            **page_params(start, min(page_size, 500)), "locationid": location_id,
            "group": [group.upper()], "managedap": False,
            "activestatus": True if active_only else None,
        }
        data = await get_client().get("/aps", params=params)
        rows = [shape_detected_ap(a) for a in rows_of(data)]
        return ok({"group": group.upper(), "total": total_of(data, len(rows)), "count": len(rows), "aps": rows})

    @mcp.tool()
    @safe
    async def cvcue_rogue_ap_summary(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
    ) -> dict:
        """
        WIPS overview: number of detected (non-managed) APs per classification,
        rogue APs with associated clients, top vendors and top SSIDs among rogues.
        """
        client = get_client()
        totals: dict[str, int] = {}
        for g in AP_GROUPS:
            data = await client.get("/aps", params={
                **page_params(0, 1), "locationid": location_id, "group": [g],
                "managedap": False, "activestatus": True,
            })
            totals[g] = total_of(data, len(rows_of(data)))
        rogues, _ = await fetch_all(client, "/aps", {
            "locationid": location_id, "group": ["ROGUE"], "managedap": False, "activestatus": True,
        }, max_items=2000)
        ssids = [{"s": s} for a in rogues for s in (a.get("ssids") or []) if isinstance(s, str)]
        return ok({
            "active_detected_aps_by_group": totals,
            "rogues_with_clients": [
                shape_detected_ap(a) for a in rogues if (a.get("numAssocClients") or 0) > 0
            ][:25],
            "rogue_vendors": counts(rogues, "vendorName"),
            "rogue_ssids": counts(ssids, "s"),
        })
