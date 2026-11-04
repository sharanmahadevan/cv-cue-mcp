"""
Hosted (multi-tenant, bring-your-own-key) mode.

The server stores no CV-CUE credentials. Every HTTP request to /mcp carries the
caller's own API key, and the server keeps a small pool of logged-in CV-CUE
sessions keyed by a hash of those credentials.

Request headers
  Authorization: Bearer <key_id>:<key_value>     (or the two headers below)
  X-CVCUE-Key-Id / X-CVCUE-Key-Value
  X-CVCUE-Base-URL     optional; auto-discovered via Launchpad when absent.
                       Must be https on an allowed host (default *.wifi.arista.com).
  X-CVCUE-CID          optional customer id for multi-customer keys
  X-CVCUE-Enable-Writes: true   opt in to mutating calls (only if the operator allows writes)

Operator environment
  CVCUE_ENABLE_WRITES          ceiling: false (default) blocks writes for everyone
  CVCUE_ALLOWED_HOST_SUFFIXES  comma list, default ".wifi.arista.com"
  CVCUE_POOL_MAX               max cached sessions (default 256)
  CVCUE_POOL_IDLE_TTL          idle seconds before a session is logged out (default 900)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .client import CvcueClient
from .config import CvcueCredentials, _truthy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-request context
# ---------------------------------------------------------------------------

@dataclass
class CallerContext:
    client: CvcueClient
    writes: bool


_current: ContextVar[CallerContext | None] = ContextVar("cvcue_caller", default=None)


def current_caller() -> CallerContext | None:
    return _current.get()


# ---------------------------------------------------------------------------
# Settings + credential parsing
# ---------------------------------------------------------------------------

@dataclass
class HostedSettings:
    allow_writes: bool = False
    allowed_host_suffixes: tuple[str, ...] = (".wifi.arista.com",)
    pool_max: int = 256
    pool_idle_ttl: float = 900.0

    @classmethod
    def from_env(cls) -> HostedSettings:
        suffixes = os.environ.get("CVCUE_ALLOWED_HOST_SUFFIXES", ".wifi.arista.com")
        return cls(
            allow_writes=_truthy(os.environ.get("CVCUE_ENABLE_WRITES"), default=False),
            allowed_host_suffixes=tuple(s.strip().lower() for s in suffixes.split(",") if s.strip()),
            pool_max=int(os.environ.get("CVCUE_POOL_MAX", "256")),
            pool_idle_ttl=float(os.environ.get("CVCUE_POOL_IDLE_TTL", "900")),
        )


class CredentialError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _check_base_url(url: str, suffixes: tuple[str, ...]) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise CredentialError(400, "X-CVCUE-Base-URL must be an https:// URL")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise CredentialError(400, "X-CVCUE-Base-URL must not contain credentials or a custom port")
    if not any(host == s.lstrip(".") or host.endswith(s if s.startswith(".") else "." + s) for s in suffixes):
        raise CredentialError(
            400, f"X-CVCUE-Base-URL host '{host}' is not allowed on this server (allowed: {', '.join(suffixes)})"
        )
    return url.strip().rstrip("/")


def parse_credentials(headers: Headers, settings: HostedSettings) -> tuple[CvcueCredentials, bool]:
    """Build caller credentials from request headers. Raises CredentialError."""
    key_id = (headers.get("x-cvcue-key-id") or "").strip()
    key_value = (headers.get("x-cvcue-key-value") or "").strip()
    auth = headers.get("authorization") or ""
    if not key_id and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        key_id, sep, key_value = token.partition(":")
        if not sep:
            raise CredentialError(401, "Bearer token must be '<key_id>:<key_value>'")
        key_id, key_value = key_id.strip(), key_value.strip()
    if not key_id or not key_value:
        raise CredentialError(
            401,
            "Missing CV-CUE credentials. Send 'Authorization: Bearer <key_id>:<key_value>' or the "
            "X-CVCUE-Key-Id and X-CVCUE-Key-Value headers (Launchpad → Admin → Keys).",
        )
    base_url = headers.get("x-cvcue-base-url") or ""
    if base_url:
        base_url = _check_base_url(base_url, settings.allowed_host_suffixes)
    creds = CvcueCredentials(
        base_url=base_url,
        key_id=key_id,
        key_value=key_value,
        cid=(headers.get("x-cvcue-cid") or "").strip(),
        verify_ssl=True,
    )
    writes = settings.allow_writes and _truthy(headers.get("x-cvcue-enable-writes"), default=False)
    return creds, writes


# ---------------------------------------------------------------------------
# Session pool
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    client: CvcueClient
    last_used: float = field(default_factory=time.monotonic)


class ClientPool:
    """Logged-in CV-CUE clients keyed by a hash of the caller's credentials."""

    def __init__(self, max_clients: int = 256, idle_ttl: float = 900.0) -> None:
        self._max = max(1, max_clients)
        self._ttl = idle_ttl
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def key_for(creds: CvcueCredentials) -> str:
        raw = "\0".join((creds.key_id, creds.key_value, creds.base_url, creds.cid))
        return hashlib.sha256(raw.encode()).hexdigest()

    def __len__(self) -> int:
        return len(self._entries)

    async def get(self, creds: CvcueCredentials) -> CvcueClient:
        key = self.key_for(creds)
        stale: list[CvcueClient] = []
        async with self._lock:
            now = time.monotonic()
            for k, e in list(self._entries.items()):
                if e.client.auth_failed or now - e.last_used > self._ttl:
                    stale.append(self._entries.pop(k).client)
            entry = self._entries.get(key)
            if entry is None:
                while len(self._entries) >= self._max:
                    oldest = min(self._entries, key=lambda k: self._entries[k].last_used)
                    stale.append(self._entries.pop(oldest).client)
                client = CvcueClient(creds)
                await client.__aenter__()
                entry = self._entries[key] = _Entry(client)
            entry.last_used = now
        for c in stale:
            asyncio.create_task(_close_quietly(c))
        return entry.client

    async def close(self) -> None:
        async with self._lock:
            clients = [e.client for e in self._entries.values()]
            self._entries.clear()
        await asyncio.gather(*(_close_quietly(c) for c in clients))


async def _close_quietly(client: CvcueClient) -> None:
    try:
        await client.__aexit__(None, None, None)
    except Exception as exc:  # pragma: no cover - best effort logout
        log.debug("Error closing pooled client: %s", exc)


# ---------------------------------------------------------------------------
# ASGI app
# ---------------------------------------------------------------------------

class CredentialMiddleware:
    """Resolve the caller's CV-CUE client for every /mcp request."""

    def __init__(self, app: ASGIApp, pool: ClientPool, settings: HostedSettings, mcp_path: str = "/mcp") -> None:
        self.app = app
        self.pool = pool
        self.settings = settings
        self.mcp_path = mcp_path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == self.mcp_path or path.startswith(self.mcp_path + "/")):
            await self.app(scope, receive, send)
            return
        try:
            creds, writes = parse_credentials(Headers(scope=scope), self.settings)
        except CredentialError as exc:
            headers = {"WWW-Authenticate": 'Bearer realm="cv-cue-mcp"'} if exc.status == 401 else None
            resp = JSONResponse({"error": str(exc)}, status_code=exc.status, headers=headers)
            await resp(scope, receive, send)
            return
        client = await self.pool.get(creds)
        token = _current.set(CallerContext(client=client, writes=writes))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


def build_app(settings: HostedSettings | None = None) -> ASGIApp:
    """Build the hosted ASGI app: /mcp (streamable HTTP), /healthz and / (info)."""
    from .server import create_server

    settings = settings or HostedSettings.from_env()
    pool = ClientPool(settings.pool_max, settings.pool_idle_ttl)
    mcp = create_server(None, hosted=True)
    inner = mcp.streamable_http_app()
    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):  # noqa: ANN001
        async with inner_lifespan(app):
            log.info(
                "Hosted mode ready — writes %s, allowed hosts %s",
                "allowed (caller opt-in)" if settings.allow_writes else "disabled",
                ", ".join(settings.allowed_host_suffixes),
            )
            try:
                yield
            finally:
                await pool.close()

    inner.router.lifespan_context = lifespan

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "sessions": len(pool)})

    async def info(_: Request) -> JSONResponse:
        body = {
            "name": "cv-cue-mcp",
            "description": "MCP server for Arista CV-CUE. Bring your own CV-CUE API key.",
            "mcp_endpoint": mcp.settings.streamable_http_path,
            "auth": "Authorization: Bearer <key_id>:<key_value> (or X-CVCUE-Key-Id + X-CVCUE-Key-Value)",
            "optional_headers": ["X-CVCUE-Base-URL", "X-CVCUE-CID", "X-CVCUE-Enable-Writes"],
            "writes_allowed": settings.allow_writes,
        }
        if os.environ.get("CVCUE_SOURCE_URL"):
            body["source"] = os.environ["CVCUE_SOURCE_URL"]
        return JSONResponse(body)

    inner.add_route("/healthz", healthz, methods=["GET"])
    inner.add_route("/", info, methods=["GET"])
    return CredentialMiddleware(inner, pool, settings, mcp.settings.streamable_http_path)
