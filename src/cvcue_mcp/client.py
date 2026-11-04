"""
Arista CV-CUE API client with session-cookie authentication.

CV-CUE is session based: POST /session with credentials returns a JSESSIONID
cookie that must accompany every later request. This client:
  - Logs in lazily on first use (so the MCP server starts even if CV-CUE is unreachable)
  - Keeps the session cookie in the httpx cookie jar
  - Re-authenticates once on HTTP 401 (session expired / idle timeout)
  - Retries 429 / 5xx / network errors with backoff
  - Sends the optional `Version` header (module API version) when asked
  - Adds the CID query parameter for multi-customer API keys
  - Discovers the CV-CUE server URL from Launchpad when CVCUE_BASE_URL is unset (API keys)
  - Logs out (DELETE /session) on shutdown
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import LAUNCHPAD_URL, CvcueCredentials

log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60.0
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]
_SESSION_TIMEOUT = 3600   # idle timeout requested at login (seconds)


class CvcueAuthError(Exception):
    """Raised when CV-CUE rejects the credentials."""


class CvcueAPIError(Exception):
    """Raised on non-2xx responses after retries are exhausted."""

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"HTTP {status} {method} {path}: {body[:300]}")


class CvcueClient:
    """Async CV-CUE API client."""

    def __init__(self, creds: CvcueCredentials, transport: httpx.AsyncBaseTransport | None = None):
        self._creds = creds
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._logged_in = False
        self.session_info: Any = None
        self.auth_failed = False      # set when CV-CUE/Launchpad rejects the credentials

    @property
    def base_url(self) -> str:
        return self._creds.base_url

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CvcueClient:
        self._http = httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            verify=self._creds.verify_ssl,
            headers={"Accept": "application/json", "User-Agent": "cv-cue-mcp"},
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is None:
            return
        if self._logged_in:
            try:
                await self._http.delete(self._url("session"), params=self._cid_params())
            except Exception as exc:  # pragma: no cover - best effort logout
                log.debug("Logout failed: %s", exc)
        await self._http.aclose()
        self._http = None
        self._logged_in = False

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._creds.base_url}/{path.lstrip('/')}"

    async def _discover_base_url(self) -> None:
        """Find the CV-CUE (Wireless Manager) server for this API key via Launchpad."""
        assert self._http is not None
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as lp:
            resp = await lp.post(
                f"{LAUNCHPAD_URL}/session",
                json=self._creds.session_body(600),
                headers={"Accept": "application/json"},
            )
            if resp.status_code in (401, 403):
                raise CvcueAuthError(f"Launchpad rejected the API key (HTTP {resp.status_code})")
            resp.raise_for_status()
            services = (await lp.get(f"{LAUNCHPAD_URL}/services")).json()
            try:
                await lp.delete(f"{LAUNCHPAD_URL}/session")
            except Exception:  # pragma: no cover - best effort
                pass
        entries = (services.get("data") or {}).get("customerServices") or []
        # service_type_id 2 = CV-CUE Wireless Manager (3 = Guest Manager)
        wm = [e for e in entries if (e.get("service") or {}).get("service_type_id") == 2]
        if not wm:
            raise CvcueAuthError(
                "Launchpad lists no CV-CUE Wireless Manager service for this key; set CVCUE_BASE_URL."
            )
        url = wm[0]["service"]["service_url"].replace("\\/", "/").rstrip("/")
        self._creds.base_url = f"{url}/wifi/api"
        log.info("Discovered CV-CUE base URL via Launchpad: %s", self._creds.base_url)

    def _cid_params(self) -> dict[str, str]:
        return {"CID": self._creds.cid} if self._creds.cid else {}

    async def login(self, force: bool = False) -> None:
        """Create a CV-CUE session (POST /session). Cookie is stored in the jar."""
        assert self._http is not None, "Client not started — use `async with CvcueClient(...)`"
        async with self._lock:
            if self._logged_in and not force:
                return
            self._http.cookies.clear()
            try:
                await self._login_locked()
            except CvcueAuthError:
                self.auth_failed = True
                raise

    async def _login_locked(self) -> None:
        assert self._http is not None
        if not self._creds.base_url:
            await self._discover_base_url()
        try:
            resp = await self._http.post(
                self._url("session"),
                json=self._creds.session_body(_SESSION_TIMEOUT),
                params=self._cid_params(),
            )
        except httpx.RequestError as exc:
            raise CvcueAuthError(
                f"Cannot reach CV-CUE at {self._creds.base_url}: {exc}. "
                "Check CVCUE_BASE_URL (CV-CUE → System → Advanced Settings → Base URLs for APIs)."
            ) from exc
        if resp.status_code in (401, 403):
            raise CvcueAuthError(
                f"CV-CUE rejected the {self._creds.auth_type} credentials "
                f"(HTTP {resp.status_code}): {resp.text[:300]}"
            )
        if resp.status_code == 404:
            raise CvcueAuthError(
                f"POST {self._creds.base_url}/session returned 404 — CVCUE_BASE_URL is probably "
                "missing the API path. Copy it from CV-CUE → System → Advanced Settings → "
                "Base URLs for APIs."
            )
        if not resp.is_success:
            raise CvcueAuthError(f"Login failed (HTTP {resp.status_code}): {resp.text[:300]}")
        try:
            self.session_info = resp.json()
        except ValueError:
            self.session_info = None
        self._logged_in = True
        log.info("CV-CUE session established → %s", self._creds.base_url)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        version: str | int | None = None,
    ) -> Any:
        """Authenticated request with re-login on 401 and retry on 429/5xx."""
        assert self._http is not None, "Client not started — use `async with CvcueClient(...)`"
        await self.login()

        query = {**self._cid_params(), **_clean_params(params)}
        headers = {"Version": str(version)} if version not in (None, "") else {}
        relogged = False

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._http.request(
                    method, self._url(path), params=query, json=json, headers=headers
                )
            except httpx.RequestError as exc:
                log.warning("Request error (attempt %d): %s", attempt + 1, exc)
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
                    continue
                raise

            if resp.status_code == 401 and not relogged:
                log.info("Session expired — re-authenticating")
                relogged = True
                await self.login(force=True)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                log.warning(
                    "HTTP %d on %s %s (attempt %d/%d)",
                    resp.status_code, method, path, attempt + 1, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
                    continue
                raise CvcueAPIError(resp.status_code, method, path, resp.text)

            if not resp.is_success:
                raise CvcueAPIError(resp.status_code, method, path, resp.text)

            if resp.headers.get("Deprecated", "").lower() == "yes":
                log.info("CV-CUE marked %s %s as deprecated", method, path)

            if resp.status_code == 204 or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return resp.text

        raise CvcueAPIError(0, method, path, "Max retries exceeded")

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> Any:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> Any:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> Any:
        return await self.request("DELETE", path, **kw)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop None values and render booleans the way the Java backend expects."""
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if v is None or v == []:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (list, tuple)):
            out[k] = ["true" if x is True else "false" if x is False else x for x in v]
        else:
            out[k] = v
    return out
