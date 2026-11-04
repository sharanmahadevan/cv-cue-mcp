"""Troubleshooting and network health tools."""

import asyncio
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import (
    err,
    hours_ago_ms,
    iso,
    norm_mac,
    now_ms,
    ok,
    page_params,
    rows_of,
    safe,
    total_of,
)
from .clients import shape_client


def register(mcp: FastMCP, get_client: Any) -> None:

    @mcp.tool()
    @safe
    async def cvcue_network_health(
        location_id: Annotated[int | None, Field(description="Location to analyse (children are broken out)")] = None,
        hours: Annotated[float, Field(description="Look-back window in hours (default 24)")] = 24,
        ssid: Annotated[list[str] | None, Field(description="Limit to SSID(s)")] = None,
    ) -> dict:
        """
        Key network health metrics for a location and each child location:
        connectivity success (association/auth/DHCP/DNS failures), performance
        (latency, retries, coverage, data rate), application experience and
        infrastructure health — the CV-CUE "Network Health" dashboard.
        """
        end = now_ms()
        data = await get_client().get("/troubleshooting/networkhealth", params={
            **page_params(0, 100), "locationid": location_id, "ssid": ssid,
            "fromtime": hours_ago_ms(hours), "totime": end,  # ms (spec says µs; server wants ms)
        })
        if not isinstance(data, dict):
            return ok(data)
        return ok({
            "hours": hours,
            "location": data.get("parentLocHealthMetrics"),
            "children": data.get("children"),
            "children_total": data.get("totalCount"),
        })

    @mcp.tool()
    @safe
    async def cvcue_client_events(
        mac_address: Annotated[str | None, Field(description="Limit to one client MAC")] = None,
        event_type: Annotated[list[str] | None, Field(description="Any of Failure, Success, Intermediate (default: Failure)")] = None,
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        hours: Annotated[float, Field(description="Look-back window in hours (default 24)")] = 24,
        ssid: Annotated[str | None, Field(description="SSID name pattern")] = None,
        ap_name: Annotated[str | None, Field(description="AP name pattern")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 100,
    ) -> dict:
        """
        Client connection event logs reported by APs (association, authentication,
        DHCP, DNS, roaming...) — defaults to failures in the last 24h.
        """
        params = {
            **page_params(start, min(page_size, 500)), "locationid": location_id,
            "clienteventtype": event_type or ["Failure"],
            "fromtime": hours_ago_ms(hours), "totime": now_ms(),
            "macpattern": norm_mac(mac_address) if mac_address else None,
            "ssidpattern": ssid, "apnamepattern": ap_name, "sortascendinglybytime": False,
        }
        data = await get_client().get("/troubleshooting/clientevents", params=params)
        rows = rows_of(data)
        return ok({"total": total_of(data, len(rows)), "count": len(rows), "events": rows})

    @mcp.tool()
    @safe
    async def cvcue_device_logs(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 100,
    ) -> dict:
        """Consolidated AP/device event logs (reboots, crashes, config, upgrades), newest first."""
        data = await get_client().get("/troubleshooting/devicelogs", params={
            **page_params(start, min(page_size, 500)), "locationid": location_id,
            "sortascending": False,
        })
        rows = rows_of(data)
        return ok({"total": total_of(data, len(rows)), "count": len(rows), "logs": rows})

    @mcp.tool()
    @safe
    async def cvcue_troubleshoot_client(
        mac_address: Annotated[str, Field(description="Client MAC address")],
        hours: Annotated[float, Field(description="Look-back window in hours (default 24)")] = 24,
    ) -> dict:
        """
        One-shot client troubleshooting: current client record, recent associations,
        connection logs, failure events and CV-CUE inferences (root-cause hints) for
        a client MAC. Sections that fail (e.g. permissions) are reported inline.
        """
        client = get_client()
        mac = norm_mac(mac_address)
        frm, to = hours_ago_ms(hours), now_ms()

        async def section(coro):
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                return {"error": f"{type(exc).__name__}: {exc}"[:300]}

        record, assoc, conn_logs, failures, inferences = await asyncio.gather(
            section(client.get("/clients", params={**page_params(0, 5), "macaddress": [mac]})),
            section(client.get(f"/clients/{mac}/associationhistory")),
            section(client.get("/clients/connectionlogs", params={
                "clientmacaddress": mac, "fromtime": frm, "totime": to, "limit": 200,
            })),
            section(client.get("/troubleshooting/clientevents", params={
                **page_params(0, 100), "macpattern": mac, "clienteventtype": ["Failure"],
                "fromtime": frm, "totime": to, "sortascendinglybytime": False,
            })),
            section(client.get(f"/troubleshooting/inferences/clients/{mac}")),
        )
        rows = rows_of(record) if not (isinstance(record, dict) and "error" in record) else []
        assoc_missing = (isinstance(assoc, list) and not assoc) or (
            isinstance(assoc, dict) and "CLIENT_RECORD_NOT_FOUND" in str(assoc.get("error", ""))
        )
        if not rows and assoc_missing:
            return err(f"Client {mac} not found in CV-CUE (no client record and no association history)")
        return ok({
            "mac": mac,
            "window": {"from": iso(frm), "to": iso(to)},
            "client": shape_client(rows[0]) if rows else record,
            "association_history": assoc,
            "connection_logs": conn_logs,
            "failure_events": failures,
            "inferences": inferences,
        })
