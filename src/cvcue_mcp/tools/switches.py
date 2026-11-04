"""Switch and wired host tools."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import ok, page_params, rows_of, safe, total_of


def register(mcp: FastMCP, get_client: Any) -> None:

    @mcp.tool()
    @safe
    async def cvcue_list_switches(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 50,
    ) -> dict:
        """
        List switches discovered via AP uplinks (LLDP): name, vendor, chassis id,
        number of APs/clients behind each, AP distribution by PoE and link speed.
        """
        data = await get_client().get(
            "/switches", params={**page_params(start, min(page_size, 500)), "locationid": location_id}
        )
        rows = rows_of(data)
        return ok({"total": total_of(data, len(rows)), "count": len(rows), "switches": rows})

    @mcp.tool()
    @safe
    async def cvcue_list_wired_clients(
        location_id: Annotated[int | None, Field(description="Scope to a location subtree")] = None,
        start: Annotated[int, Field(description="0-based record offset")] = 0,
        page_size: Annotated[int, Field(description="Records per page (max 500)")] = 50,
    ) -> dict:
        """List wired hosts seen on AP LAN ports (MAC, IP, VLAN, port, auth status, traffic)."""
        data = await get_client().get(
            "/wiredclients", params={**page_params(start, min(page_size, 500)), "locationid": location_id}
        )
        rows = rows_of(data)
        return ok({"total": total_of(data, len(rows)), "count": len(rows), "wired_clients": rows})
