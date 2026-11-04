"""SSID profile (WLAN) tools."""

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import err, ok, safe, writes_disabled
from .locations import loc_id

# WirelessProfile.apSecurityMode values (from the CV-CUE spec)
SECURITY_MODES = {
    0: "Open", 1: "WEP", 3: "WPA2", 4: "WPA/WPA2 mixed", 5: "Hotspot 2.0 OSEN",
    6: "WPA3", 7: "WPA2/WPA3 mixed", 8: "OWE",
}


def summarize_ssid(p: dict) -> dict:
    wp = p.get("wirelessProfile") or {}
    mode = wp.get("securityMode") if isinstance(wp.get("securityMode"), dict) else {}
    return {
        "templateId": p.get("templateId"),
        "profileName": p.get("templateName"),
        "ssid": p.get("ssid") or wp.get("ssid"),
        "enabled": wp.get("profileEnabled"),
        "broadcast": wp.get("ssidBroadcast"),
        "guest": wp.get("guestSSID"),
        "vlanId": wp.get("vlanId"),
        "security": SECURITY_MODES.get(wp.get("apSecurityMode"), wp.get("apSecurityMode")),
        "securityType": mode.get("type"),
        "eap8021x": wp.get("secAuthenticationEnabled"),
        "clientIsolation": wp.get("clientIsolation"),
        "associationLimit": wp.get("associationLimitValue"),
        "createdAtLocationId": loc_id(p.get("createdAtLocationId")),
        "description": p.get("description"),
    }


def register(mcp: FastMCP, get_client: Any, enable_writes: Callable[[], bool]) -> None:

    @mcp.tool()
    @safe
    async def cvcue_list_ssids(
        location_id: Annotated[int | None, Field(description="Location context (defaults to root)")] = None,
        include_subtree: Annotated[bool, Field(description="Also return profiles defined at child locations")] = True,
    ) -> dict:
        """
        List SSID profiles (WLANs): SSID name, enabled, VLAN, security mode, guest,
        client isolation and where the profile was created. Use cvcue_get_ssid for
        the full configuration.
        """
        data = await get_client().get(
            "/deviceconfiguration/ssidprofiles",
            params={"locationid": location_id, "fetchSubTreeTemplates": include_subtree},
        )
        rows = [summarize_ssid(p) for p in (data or []) if isinstance(p, dict)]
        return ok({"count": len(rows), "ssid_profiles": rows})

    @mcp.tool()
    @safe
    async def cvcue_get_ssid(
        template_id: Annotated[int, Field(description="SSID profile templateId (from cvcue_list_ssids)")],
        location_id: Annotated[int | None, Field(description="Location context")] = None,
    ) -> dict:
        """Full configuration of one SSID profile (security, network, QoS, firewall, portal...)."""
        data = await get_client().get(
            f"/deviceconfiguration/ssidprofiles/{template_id}", params={"locationid": location_id}
        )
        return ok(data)

    @mcp.tool()
    @safe
    async def cvcue_ssid_usage(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        active_only: Annotated[bool, Field(description="Only SSIDs currently broadcast")] = True,
    ) -> dict:
        """
        Live monitoring data per SSID/WLAN (GET /manageddevices/aps/wlans):
        which SSIDs are broadcast, on which bands, and how many APs/clients use them.
        """
        data = await get_client().get(
            "/manageddevices/aps/wlans", params={"locationid": location_id, "active": active_only or None}
        )
        return ok({"count": len(data or []), "wlans": data})

    @mcp.tool()
    @safe
    async def cvcue_delete_ssid(
        template_id: Annotated[int, Field(description="SSID profile templateId to delete")],
        confirm: Annotated[bool, Field(description="Must be true to proceed")] = False,
    ) -> dict:
        """
        Delete an SSID profile. Fails if the profile is still referenced by a device
        template (check GET /deviceconfiguration/ssidprofiles/{templateid}/references).
        Requires CVCUE_ENABLE_WRITES=true and confirm=true.
        """
        if not enable_writes():
            return writes_disabled()
        if not confirm:
            return err("Refusing to delete without confirm=true.")
        result = await get_client().delete(f"/deviceconfiguration/ssidprofiles/{template_id}")
        return ok(result, f"Deleted SSID profile {template_id}")
