"""
Arista CV-CUE MCP server — FastMCP setup and tool registration.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from . import prompts
from .client import CvcueClient
from .config import ServerConfig, _truthy
from .tools import _shared, aps, clients, events, execute, locations, notes, switches, troubleshooting, wlans

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
cvcue_api_schema also returns `caveats` (live-tested quirks) and `your_notes`. When you
prove a new quirk against the live API, save it with cvcue_save_endpoint_note.
List endpoints page with startindex (0-based offset) + pagesize. Time parameters
(fromtime/totime etc.) are epoch MILLISECONDS — even where the spec text says
microseconds, the server rejects µs values.

## Safety
Mutating calls need CVCUE_ENABLE_WRITES=true; destructive curated tools also need
confirm=true. Confirm with the user before rebooting, disconnecting or deleting.
With write guard on, a write returns status "confirm_required" with a preview and a
confirm_token instead of running: show the preview, wait for the user's explicit yes,
then repeat the identical call with confirm_token. Never confirm on the user's behalf.

## Response format
All tools return {ok, data, message}. Check ok==true before using data.
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
    notes.register(mcp, spec_path)
    prompts.register(mcp)


def create_server(cfg: ServerConfig) -> FastMCP:
    """
    Build the local FastMCP server: one CV-CUE client from cfg.credentials for the
    process. (The multi-tenant hosted app is built by hosted.build_app.)
    """
    _shared.REDACT_SECRETS = _truthy(os.environ.get("CVCUE_REDACT_SECRETS"), default=True)
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
    if _truthy(os.environ.get("CVCUE_WRITE_GUARD"), default=False):
        guard = _shared.GuardContext(secrets.token_bytes(32), "local",
                                     f"CV-CUE {cfg.credentials.base_url or '(auto)'} as {cfg.credentials.key_id}")
        _shared.GUARD = lambda: guard
    else:
        _shared.GUARD = _shared._no_guard
    file_notes = notes.FileNotes(os.environ.get("CVCUE_NOTES_PATH") or "~/.cvcue-mcp/notes.json")
    _shared.NOTES = lambda: file_notes
    _register_all(mcp, get_client, lambda: w, cfg.openapi_spec_path)

    log.info("Server ready — transport: %s, writes %s, write guard %s", cfg.transport,
             "ENABLED" if w else "disabled", "on" if _shared.GUARD() else "off")
    return mcp
