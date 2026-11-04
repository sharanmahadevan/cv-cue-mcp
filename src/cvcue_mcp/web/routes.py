"""Browser routes: Google sign-in, dashboard, connection management, OAuth consent."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from ..client import CvcueClient
from ..config import CvcueCredentials
from . import pages

if TYPE_CHECKING:
    from ..hosted import AppState

log = logging.getLogger(__name__)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _safe_next(url: str | None) -> str:
    """Only allow same-site relative redirects."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return "/dashboard"


def _csrf(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(24)
    return tok


async def _check_csrf(request: Request) -> dict:
    form = dict(await request.form())
    if not secrets.compare_digest(str(form.get("csrf", "")), request.session.get("csrf", "") or "-"):
        raise PermissionError("Your session expired. Reload the page and try again.")
    return form


def build_routes(state: AppState) -> list[Route]:
    store, provider, cfg = state.store, state.provider, state.settings

    async def db(fn, *a):  # noqa: ANN001, ANN202
        return await asyncio.to_thread(fn, *a)

    async def current_user(request: Request):  # noqa: ANN202
        uid = request.session.get("uid")
        return await db(store.get_user, uid) if uid else None

    def html(body: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(body, status, headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                       "img-src 'self' data:; form-action 'self' https: http://localhost:* http://127.0.0.1:*; "
                                       "frame-ancestors 'none'",
            "Referrer-Policy": "same-origin",
        })

    def flash(request: Request, kind: str, text: str) -> None:
        request.session["flash"] = [kind, text]

    # ---------------------------------------------------------------- landing

    async def home(request: Request) -> Response:
        if await current_user(request):
            return RedirectResponse("/dashboard", 303)
        return html(pages.landing(_safe_next(request.query_params.get("next")), cfg.google_enabled,
                                  cfg.dev_login, request.query_params.get("error")))

    async def legal(request: Request) -> Response:
        return html(pages.legal(request.url.path.strip("/")))

    # ----------------------------------------------------------- google login

    async def google_start(request: Request) -> Response:
        if not cfg.google_enabled:
            return RedirectResponse("/?error=Google+sign-in+is+not+configured", 303)
        if request.query_params.get("agree") != "1":
            return RedirectResponse("/?error=Please+accept+the+terms+to+continue", 303)
        st = secrets.token_urlsafe(24)
        request.session["g_state"] = st
        request.session["next"] = _safe_next(request.query_params.get("next"))
        q = urlencode({
            "client_id": cfg.google_client_id, "redirect_uri": f"{cfg.public_url}/auth/google/callback",
            "response_type": "code", "scope": "openid email profile", "state": st, "prompt": "select_account",
        })
        return RedirectResponse(f"{GOOGLE_AUTH}?{q}", 303)

    async def google_callback(request: Request) -> Response:
        p = request.query_params
        st = request.session.pop("g_state", None)
        if not st or not secrets.compare_digest(p.get("state", ""), st):
            return RedirectResponse("/?error=Sign-in+expired%2C+please+try+again", 303)
        if p.get("error") or not p.get("code"):
            return RedirectResponse("/?error=Google+sign-in+was+cancelled", 303)
        try:
            async with httpx.AsyncClient(timeout=15) as h:
                tok = (await h.post(GOOGLE_TOKEN, data={
                    "code": p["code"], "client_id": cfg.google_client_id, "client_secret": cfg.google_client_secret,
                    "redirect_uri": f"{cfg.public_url}/auth/google/callback", "grant_type": "authorization_code",
                })).raise_for_status().json()
                info = (await h.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"})
                        ).raise_for_status().json()
        except Exception as exc:  # noqa: BLE001
            log.warning("Google sign-in failed: %s", exc)
            return RedirectResponse("/?error=Google+sign-in+failed", 303)
        if not info.get("sub") or not info.get("email") or not info.get("email_verified"):
            return RedirectResponse("/?error=Your+Google+email+is+not+verified", 303)
        user = await db(store.upsert_user, info["sub"], info["email"], info.get("name"))
        nxt = _safe_next(request.session.get("next"))
        request.session.clear()
        request.session["uid"] = user.id
        return RedirectResponse(nxt, 303)

    async def dev_login(request: Request) -> Response:
        if not cfg.dev_login:
            return Response(status_code=404)
        form = dict(await request.form())
        email = str(form.get("email", "")).strip()[:120] or "dev@example.com"
        user = await db(store.upsert_user, f"dev:{email}", email, "Developer")
        request.session.clear()
        request.session["uid"] = user.id
        return RedirectResponse(_safe_next(str(form.get("next", ""))), 303)

    async def logout(request: Request) -> Response:
        try:
            await _check_csrf(request)
        except PermissionError:
            pass
        request.session.clear()
        return RedirectResponse("/", 303)

    # -------------------------------------------------------------- dashboard

    async def dashboard(request: Request) -> Response:
        user = await current_user(request)
        if not user:
            return RedirectResponse("/?next=/dashboard", 303)
        rid = request.query_params.get("return")
        if rid:
            request.session["return_to"] = f"/consent?request={rid}"
        conns = await db(store.list_connections, user.id)
        grants = await db(store.active_grants, user.id)
        fl = request.session.pop("flash", None)
        return html(pages.dashboard(user, conns, grants, _csrf(request), f"{cfg.public_url}/mcp",
                                    cfg.allow_writes, tuple(fl) if fl else None))

    async def _test(user_id: str, conn) -> tuple[bool, str]:  # noqa: ANN001
        creds = CvcueCredentials(base_url=conn.base_url, key_id=conn.key_id,
                                 key_value=await db(store.key_value, conn), cid=conn.cid)
        try:
            async with CvcueClient(creds) as c:
                s = await c.get("/session")
                v = await c.get("/system/version")
            role = (s or {}).get("role", "?") if isinstance(s, dict) else "?"
            ver = (v or {}).get("version", "?") if isinstance(v, dict) else "?"
            ok, msg = True, f"Connected as {role}, CV-CUE {ver}"
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, str(exc).split(":", 1)[-1].strip()[:200] or type(exc).__name__
        await db(store.record_test, user_id, conn.id, ok, msg)
        return ok, msg

    async def add_connection(request: Request) -> Response:
        user = await current_user(request)
        if not user:
            return RedirectResponse("/", 303)
        try:
            f = await _check_csrf(request)
        except PermissionError as exc:
            flash(request, "err", str(exc))
            return RedirectResponse("/dashboard", 303)
        name, key_id, key_value = (str(f.get(k, "")).strip() for k in ("name", "key_id", "key_value"))
        base_url, cid = str(f.get("base_url", "")).strip(), str(f.get("cid", "")).strip()
        if not (name and key_id and key_value):
            flash(request, "err", "Name, key ID and key value are required.")
            return RedirectResponse("/dashboard", 303)
        if base_url:
            from ..hosted import CredentialError, check_base_url
            try:
                base_url = check_base_url(base_url, cfg.allowed_host_suffixes)
            except CredentialError as exc:
                flash(request, "err", str(exc).replace("X-CVCUE-Base-URL", "Base URL"))
                return RedirectResponse("/dashboard", 303)
        conn = await db(store.add_connection, user.id, name[:60], key_id, key_value, base_url, cid,
                        cfg.allow_writes and f.get("allow_writes") == "1")
        ok, msg = await _test(user.id, conn)
        flash(request, "ok" if ok else "err",
              f"Saved “{name}”. " + (msg if ok else f"Test failed: {msg}. Check the key, then test again."))
        back = request.session.pop("return_to", None)
        return RedirectResponse(back if ok and back else "/dashboard", 303)

    async def conn_action(request: Request) -> Response:
        user = await current_user(request)
        if not user:
            return RedirectResponse("/", 303)
        try:
            f = await _check_csrf(request)
        except PermissionError as exc:
            flash(request, "err", str(exc))
            return RedirectResponse("/dashboard", 303)
        cid, action = request.path_params["cid"], request.path_params["action"]
        conn = await db(store.get_connection, user.id, cid)
        if not conn:
            flash(request, "err", "Connection not found.")
        elif action == "test":
            ok, msg = await _test(user.id, conn)
            flash(request, "ok" if ok else "err", f"{conn.name}: {msg}")
        elif action == "default":
            await db(store.set_default, user.id, cid)
            flash(request, "ok", f"Claude will now use “{conn.name}”.")
        elif action == "writes" and cfg.allow_writes:
            allow = f.get("allow") == "1"
            await db(store.set_writes, user.id, cid, allow)
            state.pool.forget_connection(cid)
            flash(request, "ok", f"Writes {'enabled' if allow else 'disabled'} for “{conn.name}”.")
        elif action == "delete":
            await db(store.delete_connection, user.id, cid)
            state.pool.forget_connection(cid)
            flash(request, "ok", f"Deleted “{conn.name}”.")
        return RedirectResponse("/dashboard", 303)

    async def revoke_grant(request: Request) -> Response:
        user = await current_user(request)
        if user:
            try:
                f = await _check_csrf(request)
                await db(store.revoke_client_for_user, user.id, str(f.get("client_id", "")))
                flash(request, "ok", "Disconnected. That app must be approved again to use your connections.")
            except PermissionError as exc:
                flash(request, "err", str(exc))
        return RedirectResponse("/dashboard", 303)

    async def delete_account(request: Request) -> Response:
        user = await current_user(request)
        if user:
            try:
                await _check_csrf(request)
            except PermissionError as exc:
                flash(request, "err", str(exc))
                return RedirectResponse("/dashboard", 303)
            for c in await db(store.list_connections, user.id):
                state.pool.forget_connection(c.id)
            await db(store.delete_user, user.id)
            request.session.clear()
        return html(pages.message("Account deleted", "Your account, stored keys and app approvals are gone.", "/", "Home"))

    # ---------------------------------------------------------------- consent

    async def consent_get(request: Request) -> Response:
        rid = request.query_params.get("request", "")
        req = await db(store.get_request, rid)
        if req is None:
            return html(pages.message("Request expired", "This approval link has expired. Start again from your app."), 400)
        user = await current_user(request)
        if not user:
            return RedirectResponse(f"/?next=/consent%3Frequest%3D{rid}", 303)
        client_id, params = req
        client = await db(store.get_client, client_id) or {}
        conns = await db(store.list_connections, user.id)
        default = next((c for c in conns if c.is_default), conns[0] if conns else None)
        return html(pages.consent(user, client.get("client_name") or "An MCP client",
                                  urlsplit(params["redirect_uri"]).netloc, rid, _csrf(request), default, len(conns)))

    async def consent_post(request: Request) -> Response:
        user = await current_user(request)
        if not user:
            return RedirectResponse("/", 303)
        try:
            f = await _check_csrf(request)
        except PermissionError as exc:
            return html(pages.message("Session expired", str(exc)), 400)
        rid = str(f.get("request", ""))
        if f.get("decision") != "allow":
            url = await db(provider.deny, rid)
            return RedirectResponse(url, 303) if url else html(pages.message("Request expired", "Start again."), 400)
        if not await db(store.default_connection, user.id):
            return RedirectResponse(f"/dashboard?return={rid}", 303)
        try:
            url = await db(provider.approve, rid, user.id)
        except Exception as exc:  # noqa: BLE001
            return html(pages.message("Request expired", getattr(exc, "error_description", None) or str(exc)), 400)
        return RedirectResponse(url, 303)

    return [
        Route("/", home, methods=["GET"]),
        Route("/terms", legal, methods=["GET"]),
        Route("/privacy", legal, methods=["GET"]),
        Route("/auth/google", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/auth/dev", dev_login, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/dashboard", dashboard, methods=["GET"]),
        Route("/connections", add_connection, methods=["POST"]),
        Route("/connections/{cid}/{action}", conn_action, methods=["POST"]),
        Route("/grants/revoke", revoke_grant, methods=["POST"]),
        Route("/account/delete", delete_account, methods=["POST"]),
        Route("/consent", consent_get, methods=["GET"]),
        Route("/consent", consent_post, methods=["POST"]),
    ]
