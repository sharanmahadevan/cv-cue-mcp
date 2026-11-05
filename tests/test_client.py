import json

import httpx
import pytest

from cvcue_mcp.client import CvcueAPIError, CvcueAuthError, CvcueClient
from cvcue_mcp.config import CvcueCredentials

BASE = "https://awm.example.com/wifi/api"


def creds(**kw):
    return CvcueCredentials(base_url=kw.pop("base_url", BASE), key_id="K", key_value="V", **kw)


class FakeServer:
    """Minimal CV-CUE emulation: POST /session sets a cookie, other calls require it."""

    def __init__(self, expire_after=None):
        self.logins = 0
        self.calls = []
        self.expire_after = expire_after
        self.served = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/wifi/api/session" and request.method == "POST":
            body = json.loads(request.content)
            if body.get("keyValue") != "V":
                return httpx.Response(401, json={"errors": [{"errorCode": "BAD"}]})
            self.logins += 1
            return httpx.Response(
                201, json={"loginId": "K"}, headers={"Set-Cookie": f"JSESSIONID=s{self.logins}; Path=/"}
            )
        if "JSESSIONID" not in request.headers.get("cookie", ""):
            return httpx.Response(401)
        if self.expire_after is not None and self.served >= self.expire_after:
            self.expire_after = None
            return httpx.Response(401)
        self.served += 1
        if request.url.path.endswith("/boom"):
            return httpx.Response(400, json={"errors": [{"errorCode": "INVALID"}]})
        return httpx.Response(200, json={"path": request.url.path, "version": request.headers.get("Version")})


async def test_login_cookie_and_params():
    srv = FakeServer()
    async with CvcueClient(creds(cid="ATN1"), transport=httpx.MockTransport(srv)) as c:
        data = await c.get("/manageddevices/aps", params={"active": True, "name": ["a", "b"], "x": None})
        assert data["path"] == "/wifi/api/manageddevices/aps"
    assert srv.logins == 1
    method, path, params = srv.calls[1]
    assert params["active"] == "true" and params["CID"] == "ATN1" and "x" not in params
    assert srv.calls[-1][:2] == ("DELETE", "/wifi/api/session")   # logout on exit


async def test_relogin_on_401():
    srv = FakeServer(expire_after=1)
    async with CvcueClient(creds(), transport=httpx.MockTransport(srv)) as c:
        await c.get("/a")
        await c.get("/b")        # gets 401 once, re-logs in, succeeds
    assert srv.logins == 2


async def test_version_header():
    async with CvcueClient(creds(), transport=httpx.MockTransport(FakeServer())) as c:
        assert (await c.get("/x", version=12))["version"] == "12"
        assert (await c.get("/x"))["version"] is None


async def test_bad_credentials():
    bad = CvcueCredentials(base_url=BASE, key_id="K", key_value="nope")
    async with CvcueClient(bad, transport=httpx.MockTransport(FakeServer())) as c:
        with pytest.raises(CvcueAuthError):
            await c.get("/x")


async def test_api_error_raised():
    async with CvcueClient(creds(), transport=httpx.MockTransport(FakeServer())) as c:
        with pytest.raises(CvcueAPIError) as ei:
            await c.get("/boom")
        assert ei.value.status == 400


async def test_launchpad_discovery():
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "launchpad.wifi.arista.com":
            if path.endswith("/services"):
                return httpx.Response(200, json={"data": {"customerServices": [
                    {"service": {"service_type_id": 3, "service_url": "https://agm.example.com"}},
                    {"service": {"service_type_id": 2, "service_url": "https://awm9.example.com"}},
                ]}})
            return httpx.Response(200, json={})
        if path == "/wifi/api/session" and request.method == "POST":
            return httpx.Response(201, json={}, headers={"Set-Cookie": "JSESSIONID=z; Path=/"})
        return httpx.Response(200, json={"host": host})

    c = CvcueClient(creds(base_url=""), transport=httpx.MockTransport(handler))
    async with c:
        assert (await c.get("/x"))["host"] == "awm9.example.com"
        assert c.base_url == "https://awm9.example.com/wifi/api"


async def test_post_not_retried_on_5xx_but_get_is(monkeypatch):
    monkeypatch.setattr("cvcue_mcp.client._RETRY_BACKOFF", [0, 0, 0])
    hits = {"GET": 0, "POST": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/session"):
            return httpx.Response(201, json={}, headers={"Set-Cookie": "JSESSIONID=s; Path=/"})
        hits[request.method] += 1
        return httpx.Response(503)

    async with CvcueClient(creds(), transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(CvcueAPIError):
            await c.post("/manageddevices/aps/reboot", json=["AA:BB:CC:DD:EE:FF"])
        with pytest.raises(CvcueAPIError):
            await c.get("/a")
    assert hits == {"POST": 1, "GET": 3}
