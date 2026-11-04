"""
Arista CV-CUE MCP server — FastMCP setup and tool registration.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .client import CvcueClient
from .config import BUNDLED_SPEC, ServerConfig, _truthy
from .tools import _shared, aps, clients, events, execute, locations, switches, troubleshooting, wlans

log = logging.getLogger(__name__)

INSTRUCTIONS = """\
You are connected to Arista CV-CUE (CloudVision Cognitive Unified Edge), Arista's
cloud-managed Wi-Fi platform (formerly Mojo/AirTight). APs are "managed devices";
the location hierarchy (folders → floors) scopes almost everything via location_id.

## Curated tools (common operations)
  • cvcue_session_info / cvcue_server_info — connectivity, role, version, API modules
  • cvcue_list_locations / cvcue_get_location / cvcue_create_location / cvcue_delete_location
  • cvcue_list_aps / cvcue_get_ap / cvcue_ap_health_summary / cvcue_list_radios / cvcue_reboot_aps
  • cvcue_list_clients / cvcue_find_client / cvcue_client_health_summary
    cvcue_client_association_history / cvcue_disconnect_client — Wi-Fi clients
  • cvcue_list_ssids / cvcue_get_ssid / cvcue_ssid_usage / cvcue_delete_ssid — SSID profiles
  • cvcue_query_events / cvcue_event_summary — alerts and events
  • cvcue_list_rogue_aps / cvcue_rogue_ap_summary — WIPS (rogue / external / uncategorized APs)
  • cvcue_network_health / cvcue_client_events / cvcue_device_logs /
    cvcue_troubleshoot_client — troubleshooting
  • cvcue_list_switches / cvcue_list_wired_clients — wired side

## Full REST API access (613 operations, 24 modules)
For anything else (device templates, policies, RF/radio settings, reports, packet
captures, client connectivity tests, users, checkpoints, ...):
  1. cvcue_api_modules  → browse modules
  2. cvcue_api_search   → find endpoints by keyword
  3. cvcue_api_schema   → parameters + request/response schema
  4. cvcue_api_execute  → call the endpoint
List endpoints page with startindex (0-based offset) + pagesize. Time parameters
(fromtime/totime etc.) are epoch MILLISECONDS — even where the spec text says
microseconds, the server rejects µs values.

## Safety
Mutating calls need CVCUE_ENABLE_WRITES=true; destructive curated tools also need
confirm=true. Confirm with the user before rebooting, disconnecting or deleting.

## Response format
All tools return {ok, data, message}. Check ok==true before using data.
"""


HOSTED_NOTE = """
## Hosted mode
This server is shared: each connection uses the caller's own CV-CUE API key.
Writes are only possible when the caller sent 'X-CVCUE-Enable-Writes: true'
and the operator allows writes. Secret values are returned as ***REDACTED***.
"""


def _register_all(mcp: FastMCP, get_client: Callable[[], CvcueClient], writes: Callable[[], bool],
                  spec_path: str) -> None:
    locations.register(mcp, get_client, writes)
    aps.register(mcp, get_client, writes)
    clients.register(mcp, get_client, writes)
    wlans.register(mcp, get_client, writes)
    events.register(mcp, get_client)
    troubleshooting.register(mcp, get_client)
    switches.register(mcp, get_client)
    execute.register(mcp, get_client, spec_path=spec_path, enable_writes=writes)


def create_server(cfg: ServerConfig | None, *, hosted: bool = False) -> FastMCP:
    """
    Build the FastMCP server.

    Local mode (default): one CV-CUE client from cfg.credentials for the process.
    Hosted mode: no stored credentials; each request's client comes from
    hosted.CredentialMiddleware (bring-your-own-key).
    """
    _shared.REDACT_SECRETS = _truthy(os.environ.get("CVCUE_REDACT_SECRETS"), default=True)

    if hosted:
        from .hosted import current_caller

        def hosted_client() -> CvcueClient:
            caller = current_caller()
            if caller is None:
                raise RuntimeError("No CV-CUE credentials on this request (send your API key in the headers)")
            return caller.client

        def hosted_writes() -> bool:
            caller = current_caller()
            return bool(caller and caller.writes)

        mcp = FastMCP(
            name="cv-cue-mcp",
            instructions=INSTRUCTIONS + HOSTED_NOTE,
            stateless_http=True,
            json_response=True,
            # Public server behind Fly's proxy: Host is the public hostname, not localhost.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        spec = os.environ.get("CVCUE_OPENAPI_SPEC") or str(BUNDLED_SPEC)
        _register_all(mcp, hosted_client, hosted_writes, spec)
        log.info("Server ready — hosted (bring-your-own-key) mode")
        return mcp

    assert cfg is not None, "cfg is required in local mode"
    state: dict = {"client": None}

    @asynccontextmanager
    async def lifespan(app: FastMCP) -> AsyncIterator[dict]:  # noqa: ARG001
        async with CvcueClient(cfg.credentials) as c:
            state["client"] = c
            log.info("CV-CUE client ready → %s", cfg.credentials.base_url or "(Launchpad discovery)")
            yield {"client": c}
        state["client"] = None
        log.info("CV-CUE client closed")

    def get_client() -> CvcueClient:
        client = state["client"]
        if client is None:
            raise RuntimeError("CV-CUE client is not initialised — server still starting up")
        return client

    mcp = FastMCP(name="cv-cue-mcp", instructions=INSTRUCTIONS, lifespan=lifespan)

    w = cfg.enable_writes
    _register_all(mcp, get_client, lambda: w, cfg.openapi_spec_path)

    log.info("Server ready — transport: %s, writes %s", cfg.transport, "ENABLED" if w else "disabled")
    return mcp
