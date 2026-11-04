import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.datastructures import Headers

from cvcue_mcp.client import CvcueClient
from cvcue_mcp.hosted import CredentialError, HostedSettings, build_app, check_base_url, parse_byok
from cvcue_mcp.tools import _shared
from cvcue_mcp.web.store import Cipher, Store

BASE = "https://awm1.srv.wifi.arista.com/wifi/api"
PUBLIC = "http://localhost:8080"
TREE = {"rootLocationId": {"type": "locallocationid", "id": 0},
        "locations": {'{"type":"locallocationid","id":0}': {
            "type": "folderlocation", "name": "Root", "parentId": None}}}

logins: list[str] = []


def upstream(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/wifi/api")
    if p == "/session" and request.method == "POST":
        key = json.loads(request.content)["keyId"]
        if key.startswith("BAD"):
            return httpx.Response(401, json={"error": "bad key"})
        logins.append(key)
        return httpx.Response(201, json={}, headers={"Set-Cookie": f"JSESSIONID={key}; Path=/"})
    if p == "/session":
        return httpx.Response(200, json={"role": "ADMINISTRATOR"})
    if p == "/system/version":
        return httpx.Response(200, json={"version": "2026.10.23"})
    if p == "/locations/tree":
        return httpx.Response(200, json=TREE)
    if p == "/locations" and request.method == "POST":
        return httpx.Response(200, json={"type": "folderlocation", "id": {"type": "locallocationid", "id": 0},
                                         "children": [{"type": "folderlocation", "name": "New",
                                                       "id": {"type": "locallocationid", "id": 9}}]})
    if p == "/ssid":
        return httpx.Response(200, json={"pskPassphrase": "hunter2", "radiusSettingsPasswordOption": 0,
                                         "coaSecret": None, "nested": [{"authPrimaryRadiusSecret": "s3"}]})
    if p == "/big":
        return httpx.Response(200, json=[{"x": "y" * 1000}] * 200)
    return httpx.Response(200, json={})


@pytest.fixture(autouse=True)
def mock_upstream(monkeypatch):
    logins.clear()
    orig = CvcueClient.__init__

    def patched(self, creds, transport=None):
        orig(self, creds, transport=httpx.MockTransport(upstream))

    monkeypatch.setattr(CvcueClient, "__init__", patched)


def settings(**kw):
    base = dict(public_url=PUBLIC, master_key=Cipher.generate_key(), session_secret="test-secret",
                db_path=":memory:", dev_login=True)
    base.update(kw)
    return HostedSettings(**base)


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class Hosted:
    def __init__(self, s):
        self.app = build_app(s)

    async def __aenter__(self):
        inner = self.app.inner
        self._ls = inner.router.lifespan_context(inner)
        await self._ls.__aenter__()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=PUBLIC,
                                      follow_redirects=False)
        return self

    async def __aexit__(self, *exc):
        await self.http.aclose()
        await self._ls.__aexit__(*exc)

    async def call(self, tool, args=None, auth=None, **extra):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
        h = {**MCP_HEADERS, **extra}
        if auth:
            h["Authorization"] = f"Bearer {auth}"
        r = await self.http.post("/mcp", json=body, headers=h)
        assert r.status_code == 200, r.text
        return json.loads(r.json()["result"]["content"][0]["text"])

    def csrf(self, html: str) -> str:
        return re.search(r'name=csrf value="([^"]+)"', html).group(1)

    async def dev_login(self, email="ada@example.com"):
        r = await self.http.post("/auth/dev", data={"email": email, "next": "/dashboard"})
        assert r.status_code == 303

    async def add_connection(self, name="HQ", key="K1", writes=False):
        page = (await self.http.get("/dashboard")).text
        data = {"csrf": self.csrf(page), "name": name, "key_id": key, "key_value": "v", "base_url": BASE}
        if writes:
            data["allow_writes"] = "1"
        r = await self.http.post("/connections", data=data)
        assert r.status_code == 303
        return r

    async def oauth(self):
        """Run DCR + authorize + consent + token exchange like Claude does. Returns the token response."""
        reg = (await self.http.post("/register", json={
            "client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none"})).json()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        r = await self.http.get("/authorize", params={
            "response_type": "code", "client_id": reg["client_id"], "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "cvcue",
            "resource": f"{PUBLIC}/mcp"})
        assert r.status_code == 302, r.text
        consent_url = r.headers["location"]
        assert consent_url.startswith(f"{PUBLIC}/consent?request=")
        page = await self.http.get(consent_url)
        assert page.status_code == 200 and "Approve access" in page.text and "Claude" in page.text
        rid = parse_qs(urlsplit(consent_url).query)["request"][0]
        r = await self.http.post("/consent", data={"csrf": self.csrf(page.text), "request": rid, "decision": "allow"})
        assert r.status_code == 303
        cb = urlsplit(r.headers["location"])
        assert cb.netloc == "claude.ai"
        q = parse_qs(cb.query)
        assert q["state"] == ["xyz"]
        tok = (await self.http.post("/token", data={
            "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "client_id": reg["client_id"], "code_verifier": verifier})).json()
        assert tok["access_token"].startswith("cvmcp_at_") and tok["refresh_token"].startswith("cvmcp_rt_")
        tok["client_id"] = reg["client_id"]
        return tok


# --- unit -----------------------------------------------------------------

def test_byok_parsing():
    s = settings(allow_writes=True)
    c, w = parse_byok("KEY-1:val:ue", Headers({"x-cvcue-enable-writes": "true"}), s)
    assert (c.key_id, c.key_value, w) == ("KEY-1", "val:ue", True)
    assert parse_byok("A:B", Headers({"x-cvcue-enable-writes": "true"}), settings())[1] is False


@pytest.mark.parametrize("url", [
    "http://x.wifi.arista.com/wifi/api", "https://evil.example.com/wifi/api", "https://wifi.arista.com.evil.io/x",
    "https://a.wifi.arista.com:8443/x", "https://u:p@a.wifi.arista.com/x",
])
def test_base_url_allowlist(url):
    with pytest.raises(CredentialError):
        check_base_url(url, (".wifi.arista.com",))


def test_store_encrypts_and_isolates():
    st = Store(":memory:", Cipher(Cipher.generate_key()))
    u1, u2 = st.upsert_user("g1", "a@x", None), st.upsert_user("g2", "b@x", None)
    c = st.add_connection(u1.id, "HQ", "KID", "super-secret")
    raw = st._q("SELECT key_value_enc FROM connections")[0][0]
    assert b"super-secret" not in raw
    assert st.key_value(c) == "super-secret"
    assert st.get_connection(u2.id, c.id) is None             # other users can't see it
    assert st.default_connection(u1.id).id == c.id


def test_wrong_master_key_cannot_decrypt():
    path = ":memory:"
    st = Store(path, Cipher(Cipher.generate_key()))
    u = st.upsert_user("g", "a@x", None)
    c = st.add_connection(u.id, "HQ", "KID", "secret")
    st.cipher = Cipher(Cipher.generate_key())
    with pytest.raises(Exception):
        st.key_value(c)


# --- web + OAuth ------------------------------------------------------------

async def test_public_pages_and_metadata():
    async with Hosted(settings()) as h:
        r = await h.http.get("/")
        assert r.status_code == 200 and "Arista CV-CUE" in r.text
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert (await h.http.get("/terms")).status_code == 200
        md = (await h.http.get("/.well-known/oauth-authorization-server")).json()
        assert md["registration_endpoint"].endswith("/register") and "S256" in md["code_challenge_methods_supported"]
        pr = (await h.http.get("/.well-known/oauth-protected-resource/mcp")).json()
        assert pr["resource"] == f"{PUBLIC}/mcp"
        r = await h.http.post("/mcp", json={}, headers=MCP_HEADERS)
        assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
        assert (await h.http.get("/dashboard")).status_code == 303          # needs sign-in


async def test_dashboard_requires_csrf():
    async with Hosted(settings()) as h:
        await h.dev_login()
        r = await h.http.post("/connections", data={"csrf": "wrong", "name": "x", "key_id": "K", "key_value": "v"})
        assert r.status_code == 303
        page = (await h.http.get("/dashboard")).text
        assert "session expired" in page.lower() and "No connections yet" in page


async def test_full_oauth_flow_and_tools():
    async with Hosted(settings(allow_writes=True)) as h:
        await h.dev_login()
        await h.add_connection("HQ", "K1")
        page = (await h.http.get("/dashboard")).text
        assert "Connected as ADMINISTRATOR" in page and "v" not in re.findall(r"<code>([^<]*)</code>", page)
        tok = await h.oauth()
        at = tok["access_token"]
        d = await h.call("cvcue_list_locations", auth=at)
        assert d["ok"] and logins[-1] == "K1"
        # writes: connection is read-only by default
        d = await h.call("cvcue_create_location", {"name": "New", "parent_id": 0}, auth=at)
        assert not d["ok"] and "disabled" in d["message"]
        # second connection + switching from Claude
        await h.add_connection("Lab", "K2", writes=True)
        d = await h.call("cvcue_list_connections", auth=at)
        assert [c["name"] for c in d["data"]["connections"]] == ["HQ", "Lab"] and d["data"]["in_use"] == "HQ"
        d = await h.call("cvcue_use_connection", {"name": "lab"}, auth=at)
        assert d["ok"]
        d = await h.call("cvcue_create_location", {"name": "New", "parent_id": 0}, auth=at)
        assert d["ok"] and d["data"]["id"] == 9 and logins[-1] == "K2"
        # refresh rotates tokens; old access token stops working
        new = (await h.http.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                 "client_id": tok["client_id"]})).json()
        assert new["access_token"] != at
        r = await h.http.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": f"Bearer {at}"})
        assert r.status_code == 401
        assert (await h.call("cvcue_list_locations", auth=new["access_token"]))["ok"]
        # disconnect from dashboard revokes it
        page = (await h.http.get("/dashboard")).text
        assert "Claude" in page
        await h.http.post("/grants/revoke", data={"csrf": h.csrf(page), "client_id": tok["client_id"]})
        r = await h.http.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Bearer " + new["access_token"]}
                              )
        assert r.status_code == 401


async def test_oauth_user_without_connection_gets_clear_error():
    async with Hosted(settings()) as h:
        await h.dev_login()
        page = await h.http.get("/consent?request=nope")
        assert page.status_code == 400
        await h.add_connection("HQ", "K1")
        tok = await h.oauth()
        page = (await h.http.get("/dashboard")).text
        for cid in re.findall(r'/connections/(c_[^/]+)/delete', page):
            await h.http.post(f"/connections/{cid}/delete", data={"csrf": h.csrf(page)})
        d = await h.call("cvcue_list_locations", auth=tok["access_token"])
        assert not d["ok"] and "/dashboard" in d["message"]


async def test_users_are_isolated():
    async with Hosted(settings()) as h:
        await h.dev_login("ada@example.com")
        await h.add_connection("Ada", "KA")
        ada = await h.oauth()
        h.http.cookies.clear()
        await h.dev_login("bob@example.com")
        await h.add_connection("Bob", "KB")
        bob = await h.oauth()
        assert (await h.call("cvcue_list_connections", auth=ada["access_token"]))["data"]["in_use"] == "Ada"
        assert (await h.call("cvcue_list_connections", auth=bob["access_token"]))["data"]["in_use"] == "Bob"
        await h.call("cvcue_list_locations", auth=bob["access_token"])
        assert logins[-1] == "KB"


async def test_delete_account_revokes_everything():
    async with Hosted(settings()) as h:
        await h.dev_login()
        await h.add_connection()
        tok = await h.oauth()
        page = (await h.http.get("/dashboard")).text
        r = await h.http.post("/account/delete", data={"csrf": h.csrf(page)})
        assert "Account deleted" in r.text
        r = await h.http.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Bearer " + tok["access_token"]}
                              )
        assert r.status_code == 401


# --- bring your own key -------------------------------------------------------

async def test_byok_still_works():
    async with Hosted(settings(allow_writes=True)) as h:
        d = await h.call("cvcue_list_locations", auth="K9:secret", **{"X-CVCUE-Base-URL": BASE})
        assert d["ok"] and logins == ["K9"]
        d = await h.call("cvcue_list_locations", **{"X-CVCUE-Key-Id": "K8", "X-CVCUE-Key-Value": "v",
                                                    "X-CVCUE-Base-URL": BASE})
        assert d["ok"] and logins[-1] == "K8"
        d = await h.call("cvcue_list_connections", auth="K9:secret", **{"X-CVCUE-Base-URL": BASE})
        assert not d["ok"]
        r = await h.http.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Bearer A:B",
                                                         "X-CVCUE-Base-URL": "https://evil.example.com/x"})
        assert r.status_code == 400
        d = await h.call("cvcue_list_locations", auth="BAD:key", **{"X-CVCUE-Base-URL": BASE})
        assert not d["ok"] and "rejected" in d["message"]


async def test_redaction_size_cap_and_writes_byok(monkeypatch):
    from cvcue_mcp.tools import execute
    monkeypatch.setattr(execute, "MAX_RESPONSE_CHARS", 10_000)
    async with Hosted(settings(allow_writes=True)) as h:
        hb = {"X-CVCUE-Base-URL": BASE}
        d = await h.call("cvcue_api_execute", {"method": "GET", "path": "/ssid"}, auth="K:v", **hb)
        assert d["data"]["pskPassphrase"] == _shared.REDACTED and d["data"]["radiusSettingsPasswordOption"] == 0
        assert d["data"]["nested"][0]["authPrimaryRadiusSecret"] == _shared.REDACTED
        d = await h.call("cvcue_api_execute", {"method": "PUT", "path": "/ssid", "body": d["data"]}, auth="K:v",
                         **hb, **{"X-CVCUE-Enable-Writes": "true"})
        assert not d["ok"] and "placeholder" in d["message"]
        d = await h.call("cvcue_api_execute", {"method": "GET", "path": "/big"}, auth="K:v", **hb)
        assert d["status"] == 413 and d["data"]["shape"]["length"] == 200
        d = await h.call("cvcue_delete_location", {"location_id": 9, "confirm": True}, auth="K:v", **hb)
        assert not d["ok"] and "disabled" in d["message"]
