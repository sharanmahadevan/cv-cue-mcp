"""
API discovery + execute tools (code mode).

Gives the LLM the FULL CV-CUE API (613 operations across 24 modules) without
registering hundreds of tools:

  1. cvcue_api_modules  → browse modules (aps, clients, configuration, ...)
  2. cvcue_api_search   → find endpoints by keyword
  3. cvcue_api_schema   → request/response schema (with $refs resolved)
  4. cvcue_api_execute  → call any endpoint
"""


import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import _shared
from ._shared import err, ok, safe, writes_disabled

log = logging.getLogger(__name__)

METHODS = ("get", "post", "put", "patch", "delete")
_spec_cache: dict[str, dict] = {}


def load_spec(spec_path: str) -> dict | None:
    if spec_path in _spec_cache:
        return _spec_cache[spec_path]
    if not spec_path:
        return None
    try:
        spec = json.loads(Path(spec_path).expanduser().read_text())
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load OpenAPI spec from %s: %s", spec_path, exc)
        return None
    _spec_cache[spec_path] = spec
    log.info("Loaded OpenAPI spec %s (%d paths)", spec_path, len(spec.get("paths", {})))
    return spec


def resolve_refs(node: Any, spec: dict, depth: int = 0, max_depth: int = 4, seen: tuple = ()) -> Any:
    """Inline #/components/... $refs up to max_depth (cycles and deep nesting are stubbed)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            name = ref.rsplit("/", 1)[-1]
            if depth >= max_depth or ref in seen:
                return {"$ref": name}
            target: Any = spec
            for part in ref[2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            return resolve_refs(target, spec, depth + 1, max_depth, seen + (ref,))
        return {k: resolve_refs(v, spec, depth, max_depth, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(v, spec, depth, max_depth, seen) for v in node]
    return node


def _ops(spec: dict):
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method in METHODS and isinstance(op, dict):
                yield path, method, op


def _module_of(path: str, op: dict) -> str:
    tags = op.get("tags") or []
    return tags[0] if tags else path.strip("/").split("/")[0]


def register(mcp: FastMCP, get_client: Any, spec_path: str, enable_writes: Callable[[], bool]) -> None:

    @mcp.tool()
    async def cvcue_api_modules() -> dict:
        """
        List the CV-CUE API modules with operation counts (step 1 of API discovery).

        Modules group related resources: session, locations, manageddevices (your APs),
        aps (all detected APs incl. rogues), clients, configuration (policies),
        deviceconfiguration (SSID/role/RADIUS profiles, device templates), events,
        troubleshooting, system, reports, analytics, switches, users, ...
        Pass a module name as `module` to cvcue_api_search.
        """
        spec = load_spec(spec_path)
        if spec is None:
            return err("OpenAPI spec not loaded — check CVCUE_OPENAPI_SPEC.")
        desc = {t["name"]: t.get("description", "") for t in spec.get("tags", [])}
        versions = spec.get("info", {}).get("x-module-versions", {})
        stats: dict[str, dict[str, int]] = {}
        for path, method, op in _ops(spec):
            m = _module_of(path, op)
            s = stats.setdefault(m, {"operations": 0, "read": 0, "write": 0})
            s["operations"] += 1
            s["read" if method == "get" else "write"] += 1
        modules = [
            {"module": m, "name": desc.get(m, m), "spec_version": versions.get(m), **s}
            for m, s in sorted(stats.items())
        ]
        return ok({
            "total_operations": sum(s["operations"] for s in stats.values()),
            "modules": modules,
            "writes_enabled": enable_writes(),
        })

    @mcp.tool()
    async def cvcue_api_search(
        keyword: Annotated[str, Field(description="Search term, e.g. 'reboot', 'ssid', 'packet capture', 'rogue'")],
        module: Annotated[str | None, Field(description="Optional module filter (from cvcue_api_modules)")] = None,
        method_filter: Annotated[str | None, Field(description="Optional HTTP method: GET/POST/PUT/DELETE")] = None,
        limit: Annotated[int, Field(description="Max results (default 40)")] = 40,
    ) -> dict:
        """
        Search CV-CUE API endpoints (step 2 of API discovery).

        Matches every word of `keyword` against path, operationId, summary and
        description. Use cvcue_api_schema on a result before cvcue_api_execute.
        """
        spec = load_spec(spec_path)
        if spec is None:
            return err("OpenAPI spec not loaded — check CVCUE_OPENAPI_SPEC.")
        words = [w for w in keyword.lower().split() if w]
        scored = []
        for path, method, op in _ops(spec):
            if method_filter and method.upper() != method_filter.upper():
                continue
            mod = _module_of(path, op)
            if module and mod != module.lower():
                continue
            head = f"{path} {op.get('operationId', '')} {op.get('summary', '')}".lower()
            body = op.get("description", "").lower()
            if not all(w in head or w in body for w in words):
                continue
            score = sum(3 if w in path.lower() else 2 if w in head else 1 for w in words)
            scored.append((-score, path, method, {
                "method": method.upper(),
                "path": path,
                "module": mod,
                "summary": op.get("summary", ""),
                "operationId": op.get("operationId", ""),
            }))
        scored.sort(key=lambda t: t[:3])
        results = [r for *_, r in scored[: max(1, limit)]]
        return ok({
            "keyword": keyword,
            "matches": len(scored),
            "results": results,
            "note": f"Showing {len(results)} of {len(scored)}. Narrow with module/method_filter.",
        })

    @mcp.tool()
    async def cvcue_api_schema(
        path: Annotated[str, Field(description="API path exactly as in search results, e.g. '/clients/{macaddress}/associationhistory'")],
        method: Annotated[str, Field(description="HTTP method")] = "GET",
        ref_depth: Annotated[int, Field(description="How deep to inline $ref schemas (0-6, default 3)")] = 3,
    ) -> dict:
        """
        Get parameters, request body and response schema for one endpoint
        (step 3 of API discovery). Component $refs are inlined up to ref_depth.
        """
        spec = load_spec(spec_path)
        if spec is None:
            return err("OpenAPI spec not loaded — check CVCUE_OPENAPI_SPEC.")
        op = spec.get("paths", {}).get(path, {}).get(method.lower())
        if op is None:
            parts = [p for p in path.lower().split("/") if p and "{" not in p]
            cands = [
                p for p in spec.get("paths", {})
                if parts and all(x in p.lower() for x in parts)
            ]
            return err(f"{method.upper()} {path} not in spec. Close matches: {cands[:8]}")
        depth = max(0, min(ref_depth, 6))
        params = [
            {
                "name": p.get("name"),
                "in": p.get("in"),
                "required": p.get("required", False),
                "description": (p.get("description") or "")[:300],
                "schema": resolve_refs(p.get("schema", {}), spec, 0, depth),
            }
            for p in op.get("parameters", [])
            if p.get("name") != "Version"
        ]
        responses = {}
        for code, r in op.get("responses", {}).items():
            content = r.get("content", {})
            schema = next(iter(content.values()), {}).get("schema") if content else None
            responses[code] = {
                "description": r.get("description"),
                "schema": resolve_refs(schema, spec, 0, depth) if schema else None,
            }
        body = op.get("requestBody")
        return ok({
            "method": method.upper(),
            "path": path,
            "module": _module_of(path, op),
            "module_version": op.get("x-module-version"),
            "summary": op.get("summary"),
            "description": (op.get("description") or "")[:3000],
            "parameters": params,
            "requestBody": resolve_refs(body, spec, 0, depth) if body else None,
            "responses": responses,
        })

    @mcp.tool()
    @safe
    async def cvcue_api_execute(
        method: Annotated[str, Field(description="HTTP method: GET, POST, PUT, DELETE")],
        path: Annotated[str, Field(description="API path, e.g. '/manageddevices/aps' or '/clients/{macaddress}/snapshots'")],
        path_params: Annotated[dict | None, Field(description="Substitutions for {placeholders} in path")] = None,
        query_params: Annotated[dict | None, Field(description="Query parameters (lists become repeated params)")] = None,
        body: Annotated[dict | list | str | None, Field(description="JSON request body for POST/PUT/DELETE")] = None,
        version: Annotated[str | None, Field(description="Optional module API Version header (default: server latest)")] = None,
    ) -> dict:
        """
        Execute ANY CV-CUE API call (step 4 of API discovery).

        Paths are relative to the API base URL (…/wifi/api). Most list endpoints
        page with startindex (0-based offset) + pagesize, and accept locationid
        to scope results to a location subtree (see cvcue_list_locations).

        Examples:
          GET  /system/version
          GET  /manageddevices/aps   query_params={"pagesize": 20, "active": true}
          GET  /clients/{macaddress}/associationhistory  path_params={"macaddress": "AA:BB:CC:DD:EE:FF"}
          GET  /troubleshooting/clientevents  query_params={"fromtime": <epoch ms>, "pagesize": 50}

        Large responses: many GETs accept fields=[...] for a selective fetch (a field
        that doesn't support it fails with SELECTIVE_FETCH_OR_UPDATE_NOT_SUPPORTED_FOR_FIELD
        — drop that field and retry). /deviceconfiguration/devicetemplates is huge unless
        you pass modelspecific=false. Oversized results are refused with a shape preview.

        Secret values (passphrases, RADIUS secrets...) come back as ***REDACTED***.
        Never send that placeholder back in a write body — omit the field or supply
        the real value.

        Non-GET calls require writes to be enabled for this connection.
        """
        if method.upper() != "GET" and not enable_writes():
            return writes_disabled()
        if body is not None and _shared.REDACTED in json.dumps(body, default=str):
            return err(
                f"Request body contains the {_shared.REDACTED} placeholder. Remove those fields or "
                "supply real values — sending the placeholder would overwrite the real secret."
            )
        resolved = path
        for key, val in (path_params or {}).items():
            resolved = resolved.replace(f"{{{key}}}", str(val))
        if "{" in resolved:
            return err(f"Unresolved path placeholders in {resolved} — supply path_params.")
        result = await get_client().request(
            method.upper(), resolved, params=query_params, json=body, version=version
        )
        size = len(json.dumps(result, default=str))
        if size > MAX_RESPONSE_CHARS:
            return {
                "ok": False,
                "data": {"response_chars": size, "limit": MAX_RESPONSE_CHARS, "shape": _shape(result)},
                "message": (
                    f"{method.upper()} {resolved} succeeded but returned {size:,} characters (limit "
                    f"{MAX_RESPONSE_CHARS:,}). Narrow it with fields=[...], pagesize/startindex, "
                    "locationid, or modelspecific=false (device templates)."
                ),
                "status": 413,
            }
        return ok(result, f"{method.upper()} {resolved} → OK")


MAX_RESPONSE_CHARS = int(os.environ.get("CVCUE_MAX_RESPONSE_CHARS", "100000"))


def _shape(data: Any) -> Any:
    """Small structural preview of an oversized response."""
    if isinstance(data, list):
        first = data[0] if data else None
        return {"type": "list", "length": len(data),
                "item_keys": sorted(first)[:60] if isinstance(first, dict) else type(first).__name__}
    if isinstance(data, dict):
        return {"type": "object", "keys": sorted(data)[:60]}
    return type(data).__name__
