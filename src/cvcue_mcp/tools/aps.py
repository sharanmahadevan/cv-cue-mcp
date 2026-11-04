"""Managed access point (Arista AP) tools."""

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

AP_FIELDS = (
    "boxId", "name", "macaddress", "ipAddress", "model", "softwareVersion", "active",
    "locationId", "groupName", "templateName", "upSince", "assocCount", "upgradeStatus",
    "deviceConfigStatus", "configPushStatus", "connectionStatus", "powerSource", "meshEnabled",
    "networkTag", "deviceNote", "lastCrashedTime", "lowPowerSupply", "anyTunnelsDown",
)
RADIO_FIELDS = (
    "radioId", "macaddress", "protocol", "channel", "channelWidth", "txPower", "txPowerMode",
    "channelSelectionMode", "active", "clientCount", "noise", "rfUtilization", "frequencyBand",
)


def shape_ap(ap: dict) -> dict:
    out = pick(ap, AP_FIELDS)
    if "locationId" in out:
        out["locationId"] = loc_id(out["locationId"])
    radios = ap.get("radios") or []
    if radios:
        out["radios"] = [pick(r, RADIO_FIELDS) for r in radios]
    return out


def register(mcp: FastMCP, get_client: Any, enable_writes: Callable[[], bool]) -> None:

    @mcp.tool()
    @safe
    async def cvcue_list_aps(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        active: Annotated[bool | None, Field(description="true = online, false = offline")] = None,
        name: Annotated[list[str] | None, Field(description="AP name(s)")] = None,
        model: Annotated[list[str] | None, Field(description="Model(s), e.g. ['C-360']")] = None,
        software_version: Annotated[list[str] | None, Field(description="Firmware version(s)")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 50,
        include_radios: Annotated[bool, Field(description="Include per-radio details")] = False,
    ) -> dict:
        """
        List managed Arista APs (GET /manageddevices/aps) with status, model,
        firmware, IP, location and client count. Use cvcue_ap_health_summary for
        fleet-wide rollups and cvcue_get_ap for one AP.
        """
        params = {
            **page_params(start, min(page_size, 500)),
            "locationid": location_id, "active": active, "name": name, "model": model,
            "softwareversion": software_version, "fetchradios": include_radios,
            "sortby": "name",
        }
        data = await get_client().get("/manageddevices/aps", params=params)
        rows = [shape_ap(r) for r in rows_of(data)]
        return ok({"total": total_of(data, len(rows)), "start": start, "count": len(rows), "aps": rows})

    @mcp.tool()
    @safe
    async def cvcue_get_ap(
        mac_or_name: Annotated[str, Field(description="AP MAC address or exact AP name")],
    ) -> dict:
        """Get full details for one managed AP (radios, wired interfaces, mesh, health) by MAC or name."""
        client = get_client()
        looks_mac = len("".join(c for c in mac_or_name if c.isalnum())) == 12
        params = {
            **page_params(0, 5), "fetchradios": True, "populatewiredinterfaces": True,
            "populatemeshinfo": True,
        }
        if looks_mac:
            params["macaddress"] = [norm_mac(mac_or_name)]
        else:
            params["name"] = [mac_or_name]
        rows = rows_of(await client.get("/manageddevices/aps", params=params))
        if not rows:
            return err(f"No managed AP matches '{mac_or_name}'")
        ap = rows[0]
        ap["locationId"] = loc_id(ap.get("locationId"))
        return ok(ap)

    @mcp.tool()
    @safe
    async def cvcue_ap_health_summary(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
    ) -> dict:
        """
        Fleet health rollup for managed APs: online/offline counts, breakdown by
        model, firmware, upgrade/config-push status, plus lists of offline APs and
        APs with problems (crashes, low power, tunnels down, config errors).
        """
        rows, total = await fetch_all(
            get_client(), "/manageddevices/aps",
            {"locationid": location_id, "fetchradios": False},
        )
        online = [r for r in rows if r.get("active")]
        offline = [r for r in rows if not r.get("active")]
        def has_problem(r: dict) -> bool:
            statuses = f"{r.get('deviceConfigStatus', '')} {r.get('configPushStatus', '')}".upper()
            return bool(
                r.get("lowPowerSupply")
                or str(r.get("anyTunnelsDown", "")).upper() == "YES"
                or "FAIL" in statuses
                or "ERROR" in statuses
                or r.get("missingVlansDetected")
            )

        problems = [shape_ap(r) for r in rows if has_problem(r)]
        return ok({
            "total": total,
            "online": len(online),
            "offline": len(offline),
            "clients_associated": sum(int(r.get("assocCount") or 0) for r in rows),
            "by_model": counts(rows, "model"),
            "by_firmware": counts(rows, "softwareVersion"),
            "by_upgrade_status": counts(rows, "upgradeStatus"),
            "by_config_push_status": counts(rows, "configPushStatus"),
            "offline_aps": [pick(r, ("name", "macaddress", "model", "locationId", "ipAddress")) for r in offline[:50]],
            "aps_with_problems": problems[:50],
            "busiest_aps": [
                pick(r, ("name", "macaddress", "assocCount"))
                for r in sorted(online, key=lambda r: -(r.get("assocCount") or 0))[:10]
            ],
        })

    @mcp.tool()
    @safe
    async def cvcue_list_radios(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        ap_name: Annotated[list[str] | None, Field(description="Filter by AP name(s)")] = None,
        active: Annotated[bool | None, Field(description="Only active/inactive radios")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 100,
    ) -> dict:
        """
        List Wi-Fi radios across managed APs (channel, width, tx power, noise,
        RF utilization, client count) — the RF view for channel/power analysis.
        """
        params = {
            **page_params(start, min(page_size, 500)),
            "locationid": location_id, "apname": ap_name, "activestatus": active,
        }
        data = await get_client().get("/manageddevices/aps/radios", params=params)
        rows = rows_of(data)
        return ok({"total": total_of(data, len(rows)), "count": len(rows), "radios": rows})

    @mcp.tool()
    @safe
    async def cvcue_reboot_aps(
        mac_addresses: Annotated[list[str], Field(description="MAC addresses of the APs to reboot")],
        confirm: Annotated[bool, Field(description="Must be true to proceed")] = False,
    ) -> dict:
        """
        Reboot one or more managed APs (clients will be disconnected).
        Requires CVCUE_ENABLE_WRITES=true and confirm=true.
        """
        if not enable_writes():
            return writes_disabled()
        if not confirm:
            return err("Refusing to reboot without confirm=true.")
        macs = [norm_mac(m) for m in mac_addresses]
        result = await get_client().post("/manageddevices/aps/reboot", json=macs)
        return ok(result, f"Reboot requested for {len(macs)} AP(s)")
