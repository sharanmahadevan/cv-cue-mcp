import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from cvcue_mcp.client import CvcueClient
from cvcue_mcp.config import CvcueCredentials, ServerConfig
from cvcue_mcp.server import create_server
from cvcue_mcp.tools import _shared, locations

BASE = "https://awm.example.com/wifi/api"

TREE = {
    "rootLocationId": {"type": "locallocationid", "id": 0},
    "locations": {
        '{"type":"locallocationid","id":0}': {"type": "folderlocation", "name": "Root", "parentId": None},
        '{"type":"locallocationid","id":5}': {
            "type": "folderlocation", "name": "HQ", "parentId": {"type": "locallocationid", "id": 0}},
        '{"type":"locallocationid","id":7}': {
            "type": "floorlocation", "name": "Floor 1", "parentId": {"type": "locallocationid", "id": 5}},
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/wifi/api")
    if p == "/session" and request.method == "POST":
        return httpx.Response(201, json={}, headers={"Set-Cookie": "JSESSIONID=t; Path=/"})
    if p == "/locations/tree":
        return httpx.Response(200, json=TREE)
    if p == "/manageddevices/aps":
        aps = [
            {"name": "ap1", "macaddress": "00:11:74:00:00:01", "active": True, "model": "C-360",
             "softwareVersion": "18.0", "assocCount": 12, "locationId": {"type": "locallocationid", "id": 7}},
            {"name": "ap2", "macaddress": "00:11:74:00:00:02", "active": False, "model": "C-360",
             "softwareVersion": "17.0", "assocCount": 0, "lowPowerSupply": True},
        ]
        return httpx.Response(200, json={"totalCount": 2, "managedDevices": aps})
    if p == "/manageddevices/aps/reboot":
        return httpx.Response(200, json={"rebooted": json.loads(request.content)})
    return httpx.Response(200, json={})




async def call(mcp, name, args=None):
    async with create_connected_server_and_client_session(mcp._mcp_server) as s:
        r = await s.call_tool(name, args or {})
        return json.loads(r.content[0].text)


@pytest.fixture
def mock_client(monkeypatch):
    orig = CvcueClient.__init__

    def patched(self, creds, transport=None):
        orig(self, creds, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(CvcueClient, "__init__", patched)


def test_flatten_tree():
    rows = {r["id"]: r for r in locations.flatten_tree(TREE)}
    assert rows[7]["path"] == "Root / HQ / Floor 1"
    assert rows[7]["parentId"] == 5


def test_shared_helpers():
    assert _shared.norm_mac("0011.7400.00aa") == "00:11:74:00:00:AA"
    assert _shared.rows_of({"clientEvents": [1, 2]}) == [1, 2]
    assert _shared.total_of({"totalCount": 9}, 0) == 9
    assert _shared.iso(0) == 0


async def test_tool_count_and_names():
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V")))
    names = {t.name for t in await mcp.list_tools()}
    assert len(names) >= 30
    assert all(n.startswith("cvcue_") for n in names)


async def test_ap_health_summary(mock_client):
    d = await call(create_server(ServerConfig(
        credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V"))), "cvcue_ap_health_summary")
    assert d["ok"]
    data = d["data"]
    assert data["total"] == 2 and data["online"] == 1 and data["offline"] == 1
    assert data["clients_associated"] == 12
    assert data["aps_with_problems"][0]["name"] == "ap2"


async def test_writes_disabled_blocks_reboot(mock_client):
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V")))
    d = await call(mcp, "cvcue_reboot_aps", {"mac_addresses": ["00:11:74:00:00:01"], "confirm": True})
    assert not d["ok"] and "CVCUE_ENABLE_WRITES" in d["message"]
    d = await call(mcp, "cvcue_api_execute", {"method": "DELETE", "path": "/locations"})
    assert not d["ok"] and "CVCUE_ENABLE_WRITES" in d["message"]


async def test_reboot_requires_confirm(mock_client):
    mcp = create_server(ServerConfig(
        credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V"), enable_writes=True))
    d = await call(mcp, "cvcue_reboot_aps", {"mac_addresses": ["001174000001"]})
    assert not d["ok"] and "confirm" in d["message"]
    d = await call(mcp, "cvcue_reboot_aps", {"mac_addresses": ["001174000001"], "confirm": True})
    assert d["ok"] and d["data"]["rebooted"] == ["00:11:74:00:00:01"]


async def test_spec_discovery_tools():
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V")))
    d = await call(mcp, "cvcue_api_modules")
    assert d["ok"] and d["data"]["total_operations"] >= 600
    d = await call(mcp, "cvcue_api_search", {"keyword": "reboot", "method_filter": "POST"})
    assert any(r["path"] == "/manageddevices/aps/reboot" for r in d["data"]["results"])
    d = await call(mcp, "cvcue_api_schema", {"path": "/clients", "method": "GET", "ref_depth": 1})
    assert d["ok"] and any(p["name"] == "macaddress" for p in d["data"]["parameters"])
    d = await call(mcp, "cvcue_api_schema", {"path": "/nope", "method": "GET"})
    assert not d["ok"]


async def test_execute_requires_path_params(mock_client):
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V")))
    d = await call(mcp, "cvcue_api_execute", {"method": "GET", "path": "/clients/{macaddress}/snapshots"})
    assert not d["ok"] and "path_params" in d["message"]


async def test_prompts_listed_and_rendered():
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V")))
    async with create_connected_server_and_client_session(mcp._mcp_server) as s:
        prompts = (await s.list_prompts()).prompts
        assert len(prompts) == 6 and all(p.title for p in prompts)
        r = await s.get_prompt("cvcue_client_deep_dive", {"mac": "aa:bb:cc:dd:ee:ff", "hours": "6"})
        text = r.messages[0].content.text
        assert "aa:bb:cc:dd:ee:ff" in text and "6 hours" in text and "read-only" in text
        r = await s.get_prompt("cvcue_rf_health_review", {"location": "HQ"})
        assert '"HQ"' in r.messages[0].content.text


async def test_local_write_guard_and_file_notes(mock_client, monkeypatch, tmp_path):
    monkeypatch.setenv("CVCUE_WRITE_GUARD", "true")
    monkeypatch.setenv("CVCUE_NOTES_PATH", str(tmp_path / "notes.json"))
    mcp = create_server(ServerConfig(credentials=CvcueCredentials(base_url=BASE, key_id="K", key_value="V"),
                                     enable_writes=True))
    try:
        args = {"mac_addresses": ["00:11:74:00:00:01"], "confirm": True}
        d = await call(mcp, "cvcue_reboot_aps", args)
        assert d["message"].startswith("confirm_required")
        d = await call(mcp, "cvcue_reboot_aps", {**args, "confirm_token": d["data"]["guard"]["confirm_token"]})
        assert d["ok"] and d["data"]["rebooted"] == ["00:11:74:00:00:01"]
        d = await call(mcp, "cvcue_save_endpoint_note",
                       {"method": "get", "path": "/manageddevices/aps", "note": "active=true filters to online APs"})
        assert d["ok"] and (tmp_path / "notes.json").exists()
        d = await call(mcp, "cvcue_api_schema", {"path": "/manageddevices/aps"})
        assert d["data"]["your_notes"][0]["note"].startswith("active=true")
    finally:
        _shared.GUARD = _shared._no_guard
