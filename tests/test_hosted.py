import json

import httpx
import pytest
from starlette.datastructures import Headers

from cvcue_mcp import hosted
from cvcue_mcp.client import CvcueClient
from cvcue_mcp.hosted import CredentialError, HostedSettings, build_app, parse_credentials
from cvcue_mcp.tools import _shared

BASE = "https://awm1.srv.wifi.arista.com/wifi/api"

TREE = {
    "rootLocationId": {"type": "locallocationid", "id": 0},
    "locations": {
        '{"type":"locallocationid","id":0}': {"type": "folderlocation", "name": "Root", "parentId": None},
    },
}

logins: list[str] = []


def upstream(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/wifi/api")
    if p == "/session" and request.method == "POST":
        key = json.loads(request.content)["keyId"]
        if key == "BAD":
            return httpx.Response(401, json={"error": "bad key"})
        logins.append(key)
        return httpx.Response(201, json={}, headers={"Set-Cookie": f"JSESSIONID={key}; Path=/"})
    if p == "/locations/tree":
        return httpx.Response(200, json=TREE)
    if p == "/locations" and request.method == "POST":
        return httpx.Response(200, json={
            "type": "folderlocation", "id": {"type": "locallocationid", "id": 0}, "name": "Root",
            "children": [
                {"type": "folderlocation", "id": {"type": "locallocationid", "id": -1}, "name": "Staging"},
                {"type": "folderlocation", "id": {"type": "locallocationid", "id": 9}, "name": "New",
                 "timezoneId": "UTC"},
            ],
        })
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


def headers(key="K1", writes=False, **extra):
    h = {"Authorization": f"Bearer {key}:secret", "X-CVCUE-Base-URL": BASE,
         "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if writes:
        h["X-CVCUE-Enable-Writes"] = "true"
    h.update(extra)
    return h


class Hosted:
    def __init__(self, settings):
        self.app = build_app(settings)
        self.inner = self.app.app

    async def __aenter__(self):
        self._lifespan = self.inner.router.lifespan_context(self.inner)
        await self._lifespan.__aenter__()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")
        return self

    async def __aexit__(self, *exc):
        await self.http.aclose()
        await self._lifespan.__aexit__(*exc)

    async def call(self, tool, args=None, **hkw):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
        r = await self.http.post("/mcp", json=body, headers=headers(**hkw))
        assert r.status_code == 200, r.text
        return json.loads(r.json()["result"]["content"][0]["text"])


# --- header parsing ---------------------------------------------------------

def test_parse_bearer_and_headers():
    s = HostedSettings(allow_writes=True)
    c, w = parse_credentials(Headers({"authorization": "Bearer KEY-1:val:ue"}), s)
    assert (c.key_id, c.key_value, c.base_url, w) == ("KEY-1", "val:ue", "", False)
    c, w = parse_credentials(Headers({"x-cvcue-key-id": "A", "x-cvcue-key-value": "B",
                                      "x-cvcue-enable-writes": "true"}), s)
    assert (c.key_id, c.key_value, w) == ("A", "B", True)


def test_writes_need_operator_ceiling():
    h = Headers({"authorization": "Bearer A:B", "x-cvcue-enable-writes": "true"})
    assert parse_credentials(h, HostedSettings(allow_writes=False))[1] is False


@pytest.mark.parametrize("hdrs, status", [
    ({}, 401),
    ({"authorization": "Bearer onlyonepart"}, 401),
    ({"authorization": "Bearer A:B", "x-cvcue-base-url": "http://x.wifi.arista.com/wifi/api"}, 400),
    ({"authorization": "Bearer A:B", "x-cvcue-base-url": "https://evil.example.com/wifi/api"}, 400),
    ({"authorization": "Bearer A:B", "x-cvcue-base-url": "https://wifi.arista.com.evil.io/x"}, 400),
    ({"authorization": "Bearer A:B", "x-cvcue-base-url": "https://a.wifi.arista.com:8443/x"}, 400),
    ({"authorization": "Bearer A:B", "x-cvcue-base-url": "https://u:p@a.wifi.arista.com/x"}, 400),
])
def test_parse_rejects(hdrs, status):
    with pytest.raises(CredentialError) as e:
        parse_credentials(Headers(hdrs), HostedSettings())
    assert e.value.status == status


# --- ASGI app ---------------------------------------------------------------

async def test_health_and_missing_credentials():
    async with Hosted(HostedSettings()) as h:
        assert (await h.http.get("/healthz")).json()["status"] == "ok"
        assert (await h.http.get("/")).json()["mcp_endpoint"] == "/mcp"
        r = await h.http.post("/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 401 and "WWW-Authenticate" in r.headers


async def test_each_caller_gets_own_session():
    async with Hosted(HostedSettings()) as h:
        assert (await h.call("cvcue_list_locations", key="K1"))["ok"]
        assert (await h.call("cvcue_list_locations", key="K2"))["ok"]
        assert (await h.call("cvcue_list_locations", key="K1"))["ok"]
        assert logins == ["K1", "K2"]          # K1's session reused, K2 separate
        assert (await h.http.get("/healthz")).json()["sessions"] == 2


async def test_bad_key_reports_error_and_is_dropped():
    async with Hosted(HostedSettings()) as h:
        d = await h.call("cvcue_list_locations", key="BAD")
        assert not d["ok"] and "rejected" in d["message"]
        await h.call("cvcue_list_locations", key="K1")
        assert (await h.http.get("/healthz")).json()["sessions"] == 1


async def test_writes_gating():
    async with Hosted(HostedSettings(allow_writes=False)) as h:
        d = await h.call("cvcue_reboot_aps", {"mac_addresses": ["00:11:22:33:44:55"], "confirm": True}, writes=True)
        assert not d["ok"] and "X-CVCUE-Enable-Writes" in d["message"]
    async with Hosted(HostedSettings(allow_writes=True)) as h:
        d = await h.call("cvcue_delete_location", {"location_id": 9, "confirm": True})
        assert not d["ok"] and "disabled" in d["message"]           # caller didn't opt in
        d = await h.call("cvcue_create_location", {"name": "New", "parent_id": 0}, writes=True)
        assert d["ok"] and d["data"]["id"] == 9                     # new location, not the parent tree


async def test_redaction_and_placeholder_guard():
    async with Hosted(HostedSettings(allow_writes=True)) as h:
        d = await h.call("cvcue_api_execute", {"method": "GET", "path": "/ssid"})
        assert d["data"]["pskPassphrase"] == _shared.REDACTED
        assert d["data"]["nested"][0]["authPrimaryRadiusSecret"] == _shared.REDACTED
        assert d["data"]["radiusSettingsPasswordOption"] == 0 and d["data"]["coaSecret"] is None
        d = await h.call("cvcue_api_execute", {"method": "PUT", "path": "/ssid", "body": d["data"]}, writes=True)
        assert not d["ok"] and "placeholder" in d["message"]


async def test_oversized_response_refused(monkeypatch):
    from cvcue_mcp.tools import execute
    monkeypatch.setattr(execute, "MAX_RESPONSE_CHARS", 10_000)
    async with Hosted(HostedSettings()) as h:
        d = await h.call("cvcue_api_execute", {"method": "GET", "path": "/big"})
        assert not d["ok"] and d["status"] == 413 and d["data"]["shape"]["length"] == 200


def test_context_is_empty_outside_requests():
    assert hosted.current_caller() is None
