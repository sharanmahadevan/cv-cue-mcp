"""
Hosted, multi-tenant mode: a sign-in web app plus an OAuth-protected MCP endpoint.

Two ways to reach /mcp:
  1. OAuth (Claude custom connector, Claude Code /mcp login, ...)
     The user signs in with Google, saves CV-CUE API keys ("connections") in the
     dashboard, and approves the MCP client. Each request then uses the user's
     default connection. Keys are AES-GCM encrypted at rest and never sent to the client.
  2. Bring your own key (no account)
     Authorization: Bearer <key_id>:<key_value>  (or X-CVCUE-Key-Id / X-CVCUE-Key-Value)
     X-CVCUE-Base-URL, X-CVCUE-CID, X-CVCUE-Enable-Writes are optional.

Operator environment
  CVCUE_PUBLIC_URL             public origin, e.g. https://cv-cue-mcp.fly.dev (required)
  CVCUE_MASTER_KEY             32-byte base64url key encrypting stored API keys (required)
  CVCUE_SESSION_SECRET         secret for signing browser session cookies (required)
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET   Google OAuth client for sign-in
  CVCUE_DB_PATH                SQLite file (default /data/cvcue.db)
  CVCUE_ENABLE_WRITES          ceiling: false (default) keeps everything read-only
  CVCUE_ALLOWED_HOST_SUFFIXES  comma list, default ".wifi.arista.com"
  CVCUE_POOL_MAX / CVCUE_POOL_IDLE_TTL       session cache size / idle seconds
  CVCUE_DEV_LOGIN              true enables a password-less dev sign-in (localhost only)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated
from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .client import CvcueClient
from .config import BUNDLED_SPEC, CvcueCredentials, _truthy
from .tools import _shared
from .tools._shared import err, ok, safe
from .web.oauth import SCOPE, CvcueOAuthProvider, is_byok_token
from .web.store import Cipher, Store

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class HostedSettings:
    public_url: str = "http://localhost:8080"
    master_key: str = ""
    session_secret: str = ""
    db_path: str = "/data/cvcue.db"
    google_client_id: str = ""
    google_client_secret: str = ""
    dev_login: bool = False
    allow_writes: bool = False
    allowed_host_suffixes: tuple[str, ...] = (".wifi.arista.com",)
    pool_max: int = 256
    pool_idle_ttl: float = 900.0

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @classmethod
    def from_env(cls) -> HostedSettings:
        e = os.environ.get
        suffixes = e("CVCUE_ALLOWED_HOST_SUFFIXES", ".wifi.arista.com")
        s = cls(
            public_url=(e("CVCUE_PUBLIC_URL") or "").rstrip("/"),
            master_key=e("CVCUE_MASTER_KEY", ""),
            session_secret=e("CVCUE_SESSION_SECRET", ""),
            db_path=e("CVCUE_DB_PATH", "/data/cvcue.db"),
            google_client_id=e("GOOGLE_CLIENT_ID", ""),
            google_client_secret=e("GOOGLE_CLIENT_SECRET", ""),
            dev_login=_truthy(e("CVCUE_DEV_LOGIN"), default=False),
            allow_writes=_truthy(e("CVCUE_ENABLE_WRITES"), default=False),
            allowed_host_suffixes=tuple(x.strip().lower() for x in suffixes.split(",") if x.strip()),
            pool_max=int(e("CVCUE_POOL_MAX", "256")),
            pool_idle_ttl=float(e("CVCUE_POOL_IDLE_TTL", "900")),
        )
        missing = [n for n, v in (("CVCUE_PUBLIC_URL", s.public_url), ("CVCUE_MASTER_KEY", s.master_key),
                                  ("CVCUE_SESSION_SECRET", s.session_secret)) if not v]
        if missing:
            raise SystemExit(f"Hosted mode needs: {', '.join(missing)}. Generate keys with: "
                             "python -c 'import secrets;print(secrets.token_urlsafe(32))'")
        if s.dev_login and (urlsplit(s.public_url).hostname or "") not in ("localhost", "127.0.0.1"):
            raise SystemExit("CVCUE_DEV_LOGIN is only allowed when CVCUE_PUBLIC_URL is localhost")
        return s


# ---------------------------------------------------------------------------
# Bring-your-own-key parsing
# ---------------------------------------------------------------------------

class CredentialError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def check_base_url(url: str, suffixes: tuple[str, ...]) -> str:
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


def parse_byok(token: str, headers: Headers, settings: HostedSettings) -> tuple[CvcueCredentials, bool]:
    key_id, _, key_value = token.partition(":")
    key_id, key_value = key_id.strip(), key_value.strip()
    if not key_id or not key_value:
        raise CredentialError(401, "Bearer key must be '<key_id>:<key_value>'")
    base_url = headers.get("x-cvcue-base-url") or ""
    if base_url:
        base_url = check_base_url(base_url, settings.allowed_host_suffixes)
    creds = CvcueCredentials(base_url=base_url, key_id=key_id, key_value=key_value,
                             cid=(headers.get("x-cvcue-cid") or "").strip(), verify_ssl=True)
    writes = settings.allow_writes and _truthy(headers.get("x-cvcue-enable-writes"), default=False)
    return creds, writes


# ---------------------------------------------------------------------------
# Session pool
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    client: CvcueClient
    tag: str | None = None
    last_used: float = field(default_factory=time.monotonic)


class ClientPool:
    """Logged-in CV-CUE clients keyed by a hash of the credentials."""

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

    async def get(self, creds: CvcueCredentials, tag: str | None = None) -> CvcueClient:
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
                entry = self._entries[key] = _Entry(client, tag)
            entry.last_used = now
        for c in stale:
            asyncio.create_task(_close_quietly(c))
        return entry.client

    def forget_connection(self, tag: str) -> None:
        for k, e in list(self._entries.items()):
            if e.tag == tag:
                self._entries.pop(k, None)
                asyncio.create_task(_close_quietly(e.client))

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
# Per-request caller context
# ---------------------------------------------------------------------------

@dataclass
class CallerContext:
    client: CvcueClient | None
    writes: bool
    user_id: str | None = None
    connection: str | None = None
    problem: str | None = None


_current: ContextVar[CallerContext | None] = ContextVar("cvcue_caller", default=None)


def current_caller() -> CallerContext | None:
    return _current.get()


@dataclass
class AppState:
    settings: HostedSettings
    store: Store
    provider: CvcueOAuthProvider
    pool: ClientPool


class CredentialMiddleware:
    """For /mcp requests, resolve the caller's CV-CUE client before the MCP app runs."""

    def __init__(self, app: ASGIApp, state: AppState, mcp_path: str = "/mcp") -> None:
        self.app = app
        self.state = state
        self.mcp_path = mcp_path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == self.mcp_path or path.startswith(self.mcp_path + "/")):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        kid, kval = headers.get("x-cvcue-key-id"), headers.get("x-cvcue-key-value")
        if kid and kval and not headers.get("authorization"):
            MutableHeaders(scope=scope)["authorization"] = f"Bearer {kid.strip()}:{kval.strip()}"
            headers = Headers(scope=scope)
        auth = headers.get("authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        try:
            ctx = await self._resolve(token, headers)
        except CredentialError as exc:
            await JSONResponse({"error": str(exc)}, status_code=exc.status)(scope, receive, send)
            return
        reset = _current.set(ctx) if ctx else None
        try:
            await self.app(scope, receive, send)       # SDK auth middleware 401s missing/invalid tokens
        finally:
            if reset is not None:
                _current.reset(reset)

    async def _resolve(self, token: str, headers: Headers) -> CallerContext | None:
        st = self.state
        if not token:
            return None
        if is_byok_token(token):
            creds, writes = parse_byok(token, headers, st.settings)
            return CallerContext(client=await st.pool.get(creds), writes=writes)
        at = await st.provider.load_access_token(token)
        if at is None or not at.subject:
            return None
        conn = await asyncio.to_thread(st.store.default_connection, at.subject)
        if conn is None:
            return CallerContext(client=None, writes=False, user_id=at.subject,
                                 problem=f"No CV-CUE connection saved. Add one at {st.settings.public_url}/dashboard")
        creds = CvcueCredentials(base_url=conn.base_url, key_id=conn.key_id,
                                 key_value=await asyncio.to_thread(st.store.key_value, conn), cid=conn.cid)
        return CallerContext(client=await st.pool.get(creds, tag=conn.id),
                             writes=st.settings.allow_writes and conn.allow_writes,
                             user_id=at.subject, connection=conn.name)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

HOSTED_NOTE = """
## Hosted mode
Each connection uses the caller's own CV-CUE API key. Signed-in users may have several
CV-CUE connections: cvcue_list_connections shows them and cvcue_use_connection switches
the default. Writes only work when enabled for the connection (or, with a raw key, when
the caller sent 'X-CVCUE-Enable-Writes: true') and the operator allows writes.
Secret values come back as ***REDACTED***.
"""


def _client() -> CvcueClient:
    ctx = current_caller()
    if ctx is None:
        raise RuntimeError("No CV-CUE credentials on this request")
    if ctx.client is None:
        raise RuntimeError(ctx.problem or "No CV-CUE connection")
    return ctx.client


def _writes() -> bool:
    ctx = current_caller()
    return bool(ctx and ctx.writes)


def _register_connection_tools(mcp: FastMCP, state: AppState) -> None:
    @mcp.tool()
    @safe
    async def cvcue_list_connections() -> dict:
        """
        List your saved CV-CUE connections (signed-in users only) and which one is in use.
        Use cvcue_use_connection to switch before working on another CV-CUE account.
        """
        ctx = current_caller()
        if not ctx or not ctx.user_id:
            return err("Connections are only available when signed in through OAuth (not with a raw API key).")
        conns = await asyncio.to_thread(state.store.list_connections, ctx.user_id)
        return ok({
            "in_use": ctx.connection,
            "connections": [{"name": c.name, "default": c.is_default, "key_id": c.key_id_masked,
                             "server": c.base_url or "auto", "writes": c.allow_writes and state.settings.allow_writes,
                             "last_test_ok": c.last_test_ok} for c in conns],
            "manage": f"{state.settings.public_url}/dashboard",
        })

    @mcp.tool()
    @safe
    async def cvcue_use_connection(
        name: Annotated[str, Field(description="Connection name from cvcue_list_connections (case-insensitive)")],
    ) -> dict:
        """
        Make another saved connection the default. Takes effect from the NEXT tool call
        (the current call still used the previous connection).
        """
        ctx = current_caller()
        if not ctx or not ctx.user_id:
            return err("Connections are only available when signed in through OAuth.")
        conns = await asyncio.to_thread(state.store.list_connections, ctx.user_id)
        match = next((c for c in conns if c.name.lower() == name.strip().lower()), None)
        if match is None:
            return err(f"No connection named '{name}'. Available: {[c.name for c in conns]}")
        await asyncio.to_thread(state.store.set_default, ctx.user_id, match.id)
        return ok({"default": match.name}, f"Now using '{match.name}' for subsequent calls")


def build_app(settings: HostedSettings | None = None) -> ASGIApp:
    from .server import INSTRUCTIONS, _register_all
    from .web.routes import build_routes

    settings = settings or HostedSettings.from_env()
    _shared.REDACT_SECRETS = _truthy(os.environ.get("CVCUE_REDACT_SECRETS"), default=True)
    store = Store(settings.db_path, Cipher(settings.master_key))
    provider = CvcueOAuthProvider(store, settings.public_url)
    state = AppState(settings, store, provider, ClientPool(settings.pool_max, settings.pool_idle_ttl))

    mcp = FastMCP(
        name="cv-cue-mcp",
        instructions=INSTRUCTIONS + HOSTED_NOTE,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=settings.public_url,
            resource_server_url=f"{settings.public_url}/mcp",
            validate_token_resource=False,
            service_documentation_url="https://sharanmahadevan.github.io/cv-cue-mcp/",
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    _register_all(mcp, _client, _writes, os.environ.get("CVCUE_OPENAPI_SPEC") or str(BUNDLED_SPEC))
    _register_connection_tools(mcp, state)

    inner = mcp.streamable_http_app()

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "sessions": len(state.pool)})

    inner.router.routes.append(Route("/healthz", healthz, methods=["GET"]))
    inner.router.routes.extend(build_routes(state))

    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app) -> AsyncIterator[None]:  # noqa: ANN001
        async with inner_lifespan(app):
            await asyncio.to_thread(store.purge_expired)
            log.info("Hosted app ready at %s — Google sign-in %s, writes %s", settings.public_url,
                     "on" if settings.google_enabled else "OFF", "allowed" if settings.allow_writes else "disabled")
            try:
                yield
            finally:
                await state.pool.close()

    inner.router.lifespan_context = lifespan
    app = CredentialMiddleware(inner, state, mcp.settings.streamable_http_path)
    session = SessionMiddleware(app, secret_key=settings.session_secret, session_cookie="cvcue_session",
                                max_age=14 * 24 * 3600, same_site="lax",
                                https_only=settings.public_url.startswith("https://"))
    session.state = state  # type: ignore[attr-defined]  # handy for tests
    session.inner = inner  # type: ignore[attr-defined]
    session.mcp = mcp  # type: ignore[attr-defined]
    return session
