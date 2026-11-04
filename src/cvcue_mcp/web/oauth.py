"""
OAuth 2.1 authorization server for MCP clients (Claude custom connectors etc.).

The MCP SDK implements the protocol endpoints (metadata, dynamic client
registration, /authorize, /token, /revoke, PKCE checks). This provider supplies
storage and sends the user to our own sign-in + consent page at /consent.

Two kinds of bearer token are accepted on /mcp:
  cvmcp_at_…            an access token we issued to a signed-in user
  <key_id>:<key_value>  a raw CV-CUE API key (bring-your-own-key, no account)
"""

from __future__ import annotations

import asyncio
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .store import Store

ACCESS_PREFIX = "cvmcp_at_"
REFRESH_PREFIX = "cvmcp_rt_"
CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
SCOPE = "cvcue"


class PairedRefreshToken(RefreshToken):
    pair_id: str


def is_byok_token(token: str) -> bool:
    return not token.startswith((ACCESS_PREFIX, REFRESH_PREFIX)) and ":" in token


class CvcueOAuthProvider:
    def __init__(self, store: Store, public_url: str) -> None:
        self.store = store
        self.public_url = public_url.rstrip("/")

    async def _run(self, fn, *args):  # noqa: ANN001, ANN202
        return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------- clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        info = await self._run(self.store.get_client, client_id)
        return OAuthClientInformationFull.model_validate(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self._run(self.store.save_client, client_info.client_id, client_info.model_dump(mode="json"))

    # ----------------------------------------------------------- authorize

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Park the request and send the browser to our consent page."""
        rid = await self._run(self.store.save_request, client.client_id, params.model_dump(mode="json"))
        return f"{self.public_url}/consent?request={rid}"

    def approve(self, rid: str, user_id: str) -> str:
        """Called by the consent page on 'Allow'. Returns the client redirect URL with a code."""
        req = self.store.get_request(rid)
        if req is None:
            raise AuthorizeError("invalid_request", "Authorization request expired; start again from Claude.")
        client_id, p = req
        code = secrets.token_urlsafe(32)
        self.store.save_code(code, {
            "client_id": client_id,
            "user_id": user_id,
            "scopes": p.get("scopes") or [SCOPE],
            "code_challenge": p["code_challenge"],
            "redirect_uri": p["redirect_uri"],
            "redirect_uri_provided_explicitly": p["redirect_uri_provided_explicitly"],
            "resource": p.get("resource"),
            "expires_at": time.time() + CODE_TTL,
        })
        self.store.delete_request(rid)
        return construct_redirect_uri(p["redirect_uri"], code=code, state=p.get("state"))

    def deny(self, rid: str) -> str | None:
        req = self.store.get_request(rid)
        if req is None:
            return None
        _, p = req
        self.store.delete_request(rid)
        return construct_redirect_uri(
            p["redirect_uri"], error="access_denied", error_description="The user declined", state=p.get("state")
        )

    # --------------------------------------------------------------- codes

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        d = await self._run(self.store.get_code, authorization_code)
        if not d or d["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code, scopes=d["scopes"], expires_at=d["expires_at"], client_id=d["client_id"],
            code_challenge=d["code_challenge"], redirect_uri=d["redirect_uri"],
            redirect_uri_provided_explicitly=d["redirect_uri_provided_explicitly"],
            resource=d.get("resource"), subject=d["user_id"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        await self._run(self.store.delete_code, authorization_code.code)   # single use
        if not authorization_code.subject:
            raise TokenError("invalid_grant", "Authorization code has no user")
        return await self._issue(client.client_id, authorization_code.subject,
                                 authorization_code.scopes, authorization_code.resource)

    async def _issue(self, client_id: str, user_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        pair = secrets.token_urlsafe(12)
        now = time.time()

        def save() -> None:
            self.store.save_token(access, "access", client_id, user_id, scopes, resource, now + ACCESS_TTL, pair)
            self.store.save_token(refresh, "refresh", client_id, user_id, scopes, resource, now + REFRESH_TTL, pair)

        await self._run(save)
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes), refresh_token=refresh)

    # ------------------------------------------------------------- refresh

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> PairedRefreshToken | None:
        row = await self._run(self.store.get_token, refresh_token, "refresh")
        if row is None or row["client_id"] != client.client_id:
            return None
        return PairedRefreshToken(
            token=refresh_token, client_id=row["client_id"], scopes=row["scopes"].split(),
            expires_at=int(row["expires_at"]) if row["expires_at"] else None, resource=row["resource"],
            subject=row["user_id"], pair_id=row["pair_id"],
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: PairedRefreshToken, scopes: list[str]
    ) -> OAuthToken:
        await self._run(self.store.revoke_pair, refresh_token.pair_id)     # rotate
        if not refresh_token.subject:
            raise TokenError("invalid_grant", "Refresh token has no user")
        return await self._issue(client.client_id, refresh_token.subject,
                                 scopes or refresh_token.scopes, refresh_token.resource)

    # -------------------------------------------------------------- access

    async def load_access_token(self, token: str) -> AccessToken | None:
        if is_byok_token(token):
            return AccessToken(token=token, client_id="byok", scopes=[SCOPE], claims={"byok": True})
        if not token.startswith(ACCESS_PREFIX):
            return None
        row = await self._run(self.store.get_token, token, "access")
        if row is None:
            return None
        return AccessToken(
            token=token, client_id=row["client_id"], scopes=row["scopes"].split(),
            expires_at=int(row["expires_at"]) if row["expires_at"] else None, resource=row["resource"],
            subject=row["user_id"], claims={"pair_id": row["pair_id"]},
        )

    async def revoke_token(self, token: AccessToken | PairedRefreshToken) -> None:
        pair = getattr(token, "pair_id", None) or (getattr(token, "claims", None) or {}).get("pair_id")
        if pair:
            await self._run(self.store.revoke_pair, pair)
