"""Location hierarchy and system/session tools."""

import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ._shared import CONFIRM_TOKEN_HELP, err, guard_write, ok, safe, writes_disabled


def loc_id(value: Any) -> Any:
    """Flatten CV-CUE LocationId objects ({"type":"locallocationid","id":5}) to the int id."""
    if isinstance(value, dict) and "id" in value:
        return value["id"] if "childId" not in value else f"{value['id']}:{value['childId']}"
    if isinstance(value, str) and value.startswith("{"):
        try:
            return loc_id(json.loads(value))
        except ValueError:
            return value
    return value


def flatten_tree(tree: dict) -> list[dict]:
    """Turn GET /locations/tree into a flat list with full path names."""
    raw = {loc_id(k): v for k, v in (tree.get("locations") or {}).items()}
    names = {lid: v.get("name", "") for lid, v in raw.items()}
    parents = {lid: loc_id(v.get("parentId")) for lid, v in raw.items()}

    def path_of(lid: Any) -> str:
        parts, seen = [], set()
        while lid is not None and lid in names and lid not in seen:
            seen.add(lid)
            parts.append(names[lid])
            lid = parents.get(lid)
        return " / ".join(reversed(parts))

    out = []
    for lid, v in raw.items():
        out.append({
            "id": lid,
            "name": v.get("name"),
            "type": v.get("type"),
            "parentId": parents.get(lid),
            "path": path_of(lid),
            "timezone": v.get("timezoneId"),
            **({"tag": v["locationTag"]} if v.get("locationTag") else {}),
            **({"venueId": v["venueId"]} if v.get("venueId") else {}),
            **({"default": True} if v.get("defaultLocation") else {}),
        })
    out.sort(key=lambda r: r["path"])
    return out


def register(mcp: FastMCP, get_client: Any, enable_writes: Callable[[], bool]) -> None:

    @mcp.tool()
    @safe
    async def cvcue_session_info() -> dict:
        """
        Show the current CV-CUE API session: logged-in key/user, role, customer,
        timezone and allowed locations, plus the server base URL and version.
        Good first call to confirm connectivity.
        """
        client = get_client()
        session = await client.get("/session")
        version = await client.get("/system/version")
        s = session if isinstance(session, dict) else {}
        return ok({
            "base_url": client.base_url,
            "server_version": version,
            "loginId": s.get("loginId"),
            "role": s.get("role"),
            "customerId": s.get("customerId"),
            "timeZone": s.get("timeZone"),
            "sessionTimeoutSec": s.get("timeout"),
            "allowedLocations": [
                {"id": loc_id(a.get("id") or a), "name": a.get("name")} if isinstance(a, dict) else a
                for a in (s.get("allowedLocations") or [])
            ],
            "writes_enabled": enable_writes(),
        })

    @mcp.tool()
    @safe
    async def cvcue_server_info() -> dict:
        """
        CV-CUE server version, supported API module versions and server health.
        Use to check whether an endpoint/version is available on this server.
        """
        client = get_client()
        data: dict[str, Any] = {"version": await client.get("/system/version")}
        modules = await client.get("/modules")
        if isinstance(modules, dict):
            data["module_versions"] = {
                m: max((int(v["version"]) for v in vs if str(v.get("version", "")).isdigit()), default=None)
                for m, vs in modules.items() if isinstance(vs, list)
            }
        for key, path in (("health", "/system/health"), ("timestamp", "/system/timestamp")):
            try:
                data[key] = await client.get(path)
            except Exception as exc:  # noqa: BLE001 - permission dependent
                data[key] = f"unavailable: {exc}"[:200]
        return ok(data)

    @mcp.tool()
    @safe
    async def cvcue_list_locations(
        name_contains: Annotated[str | None, Field(description="Optional case-insensitive filter on name or path")] = None,
    ) -> dict:
        """
        List the CV-CUE location hierarchy (folders and floors) as a flat list with
        id, type, parentId and full path. Location ids scope most other tools via
        `location_id` (data for the whole subtree is returned).
        """
        tree = await get_client().get("/locations/tree")
        rows = flatten_tree(tree if isinstance(tree, dict) else {})
        if name_contains:
            q = name_contains.lower()
            rows = [r for r in rows if q in (r["path"] or "").lower()]
        return ok({
            "rootLocationId": loc_id((tree or {}).get("rootLocationId")),
            "count": len(rows),
            "locations": rows,
        })

    @mcp.tool()
    @safe
    async def cvcue_get_location(
        location_id: Annotated[int, Field(description="Location id (from cvcue_list_locations)")],
    ) -> dict:
        """Get one location with its path and direct children."""
        tree = await get_client().get("/locations/tree")
        rows = flatten_tree(tree if isinstance(tree, dict) else {})
        match = next((r for r in rows if r["id"] == location_id), None)
        if match is None:
            return err(f"Location {location_id} not found")
        children = [
            {"id": r["id"], "name": r["name"], "type": r["type"]}
            for r in rows if r["parentId"] == location_id
        ]
        return ok({**match, "children": children})

    @mcp.tool()
    @safe
    async def cvcue_create_location(
        name: Annotated[str, Field(description="Name of the new location")],
        parent_id: Annotated[int, Field(description="Parent location id (folders only can hold children)")],
        location_type: Annotated[str, Field(description="'folderlocation' (campus/building) or 'floorlocation'")] = "folderlocation",
        timezone_id: Annotated[str, Field(description="Java timezone id, e.g. 'America/Los_Angeles'")] = "UTC",
        venue_id: Annotated[str | None, Field(description="Optional venue id / label")] = None,
        confirm_token: Annotated[str | None, Field(description=CONFIRM_TOKEN_HELP)] = None,
    ) -> dict:
        """Create a folder or floor location under a parent. Requires CVCUE_ENABLE_WRITES=true."""
        if not enable_writes():
            return writes_disabled()
        if location_type not in ("folderlocation", "floorlocation"):
            return err("location_type must be 'folderlocation' or 'floorlocation'")
        child: dict[str, Any] = {
            "type": location_type,
            "name": name,
            "timezoneId": timezone_id,
            "venueId": venue_id or "",
        }
        if location_type == "folderlocation":
            child["children"] = []
        # POST /locations takes the PARENT folder with the new location(s) under `children`
        body = {
            "type": "folderlocation",
            "id": {"type": "locallocationid", "id": parent_id},
            "children": [child],
        }
        if g := guard_write("create_location", {"POST": "/locations", "body": body}, confirm_token):
            return g
        result = await get_client().post("/locations", json=body)
        # The API echoes the whole parent folder; pull out the location we just made.
        created = next(
            (c for c in reversed((result or {}).get("children") or [])
             if isinstance(c, dict) and c.get("name") == name and c.get("type") == location_type),
            None,
        ) if isinstance(result, dict) else None
        if created is None:
            return ok(result, f"Created {location_type} '{name}' under {parent_id} (new id not found in response)")
        new_id = loc_id(created.get("id"))
        return ok({
            "id": new_id,
            "name": created.get("name"),
            "type": created.get("type"),
            "parentId": parent_id,
            "timezone": created.get("timezoneId"),
            "venueId": created.get("venueId") or None,
        }, f"Created {location_type} '{name}' (id {new_id}) under {parent_id}")

    @mcp.tool()
    @safe
    async def cvcue_delete_location(
        location_id: Annotated[int, Field(description="Location id to delete — its child locations are deleted too")],
        confirm: Annotated[bool, Field(description="Must be true to proceed")] = False,
        confirm_token: Annotated[str | None, Field(description=CONFIRM_TOKEN_HELP)] = None,
    ) -> dict:
        """
        Delete a location AND all of its child locations. Irreversible.
        Requires CVCUE_ENABLE_WRITES=true and confirm=true.
        """
        if not enable_writes():
            return writes_disabled()
        if not confirm:
            return err("Refusing to delete without confirm=true (child locations are deleted too).")
        body = {"type": "locallocationid", "id": location_id}
        if g := guard_write("delete_location", {"DELETE": "/locations", "body": body}, confirm_token):
            return g
        result = await get_client().delete("/locations", json=body)
        return ok(result, f"Deleted location {location_id}")
