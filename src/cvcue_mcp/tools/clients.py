"""Wireless client tools."""

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import (
    counts,
    err,
    fetch_all,
    norm_mac,
    ok,
    page_params,
    pick,
    rows_of,
    safe,
    total_of,
    writes_disabled,
)
from .locations import loc_id

CLIENT_FIELDS = (
    "macAddress", "name", "userName", "ipAddress", "ipv6Addresses", "vendorName", "osType",
    "active", "vlanId", "role", "bandCapability", "bestSignalStrength", "snr", "averageDataRate",
    "poorPerformanceReasons", "captivePortalAuthStatus", "securityType", "locationId",
    "latestAssociatedApLocationId", "banned", "misbehaving", "sticky", "mloMode",
)
RADIO_FIELDS = (
    "ssid", "associatedAPName", "associatedApMac", "signalStrength", "protocol", "channel",
    "uplinkDataRate", "downlinkDataRate", "uplinkUsage", "downlinkUsage", "retryRate",
    "upSince", "connectionStatus", "smartDeviceTypeName", "misbehavingReason",
)


def shape_client(c: dict) -> dict:
    out = pick(c, CLIENT_FIELDS)
    for k in ("locationId", "latestAssociatedApLocationId"):
        if k in out:
            out[k] = loc_id(out[k])
    radio = c.get("radio")
    if isinstance(radio, dict):
        out.update(pick(radio, RADIO_FIELDS))
    return out


def _signal_bucket(c: dict) -> str | None:
    rssi = (c.get("radio") or {}).get("signalStrength") or c.get("bestSignalStrength")
    if not isinstance(rssi, (int, float)) or rssi == 0:
        return None
    if rssi >= -60:
        return "excellent (>= -60 dBm)"
    if rssi >= -70:
        return "good (-60..-70 dBm)"
    if rssi >= -80:
        return "fair (-70..-80 dBm)"
    return "poor (< -80 dBm)"


def register(mcp: FastMCP, get_client: Any, enable_writes: Callable[[], bool]) -> None:

    @mcp.tool()
    @safe
    async def cvcue_list_clients(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        active: Annotated[bool | None, Field(description="true = currently connected (default), false = disconnected/historic")] = True,
        ssid: Annotated[list[str] | None, Field(description="SSID name(s)")] = None,
        associated_ap: Annotated[list[str] | None, Field(description="Associated AP name(s)")] = None,
        username: Annotated[list[str] | None, Field(description="802.1X / portal username(s)")] = None,
        os_type: Annotated[list[str] | None, Field(description="OS type(s), e.g. ['iOS', 'Windows']")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 50,
    ) -> dict:
        """
        List Wi-Fi clients (GET /clients) with SSID, AP, signal, protocol, data
        rates, IP, username and OS. Defaults to currently connected clients.
        """
        params = {
            **page_params(start, min(page_size, 500)),
            "locationid": location_id, "activestatus": active, "ssid": ssid,
            "associatedap": associated_ap, "username": username, "ostype": os_type,
        }
        data = await get_client().get("/clients", params=params)
        rows = [shape_client(c) for c in rows_of(data)]
        return ok({"total": total_of(data, len(rows)), "start": start, "count": len(rows), "clients": rows})

    @mcp.tool()
    @safe
    async def cvcue_find_client(
        query: Annotated[str, Field(description="Client MAC, IP address, username or device name")],
    ) -> dict:
        """
        Find a client by MAC, IP, username or device name (active or recently seen).
        Tries the most specific field first and returns all matches.
        """
        client = get_client()
        q = query.strip()
        hexes = "".join(ch for ch in q if ch.isalnum())
        if len(hexes) == 12 and all(ch in "0123456789abcdefABCDEF" for ch in hexes):
            attempts = [("macaddress", norm_mac(q))]
        elif q.count(".") == 3 or ":" in q:
            attempts = [("ipaddress", q)]
        else:
            attempts = [("username", q), ("devicename", q)]
        for field, value in attempts:
            data = await client.get("/clients", params={**page_params(0, 25), field: [value]})
            rows = rows_of(data)
            if rows:
                return ok({"matched_on": field, "count": len(rows), "clients": [shape_client(c) for c in rows]})
        return err(f"No client found for '{query}' (searched {', '.join(f for f, _ in attempts)})")

    @mcp.tool()
    @safe
    async def cvcue_client_health_summary(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
    ) -> dict:
        """
        Rollup of currently connected clients: totals by SSID, AP, protocol/band,
        OS, vendor and signal-quality bucket, plus clients with poor performance.
        """
        rows, total = await fetch_all(
            get_client(), "/clients", {"locationid": location_id, "activestatus": True}
        )

        def radio(key: str):
            return lambda c: (c.get("radio") or {}).get(key)

        poor = [shape_client(c) for c in rows if c.get("poorPerformanceReasons")]
        return ok({
            "connected_clients": total,
            "by_ssid": counts(rows, radio("ssid")),
            "by_ap": counts(rows, radio("associatedAPName")),
            "by_protocol": counts(rows, radio("protocol")),
            "by_os": counts(rows, "osType"),
            "by_vendor": counts(rows, "vendorName"),
            "by_signal": counts(rows, _signal_bucket),
            "poor_performance_count": len(poor),
            "poor_performance_reasons": counts(
                [{"r": r} for c in rows for r in (c.get("poorPerformanceReasons") or [])], "r"
            ),
            "poor_performance_clients": poor[:25],
        })

    @mcp.tool()
    @safe
    async def cvcue_client_association_history(
        mac_address: Annotated[str, Field(description="Client MAC address")],
    ) -> dict:
        """Recent associations for a client (which APs/SSIDs it joined and when)."""
        mac = norm_mac(mac_address)
        data = await get_client().get(f"/clients/{mac}/associationhistory")
        return ok({"mac": mac, "associations": data})

    @mcp.tool()
    @safe
    async def cvcue_disconnect_client(
        mac_address: Annotated[str, Field(description="Client MAC address to disconnect")],
        confirm: Annotated[bool, Field(description="Must be true to proceed")] = False,
    ) -> dict:
        """
        Force-disconnect (deauthenticate) a wireless client. The client may reconnect.
        Requires CVCUE_ENABLE_WRITES=true and confirm=true.
        """
        if not enable_writes():
            return writes_disabled()
        if not confirm:
            return err("Refusing to disconnect without confirm=true.")
        mac = norm_mac(mac_address)
        result = await get_client().post(f"/clients/{mac}/disconnectrequest")
        return ok(result, f"Disconnect requested for {mac}")
