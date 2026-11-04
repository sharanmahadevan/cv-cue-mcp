"""
Curated caveats: CV-CUE API behaviour proven against a live server that the
OpenAPI spec doesn't say (or says wrongly). cvcue_api_schema returns the ones
that match an endpoint, so Claude sees them before calling it.

Each entry: (methods, path predicate, text). methods "*" matches any method.
"""

from __future__ import annotations

from collections.abc import Callable

_TIME_PARAMS = ("fromtime", "totime", "starttime", "endtime", "from", "to")


def _has_time_param(op: dict) -> bool:
    return any((p.get("name") or "").lower() in _TIME_PARAMS for p in op.get("parameters", []))


def _has_param(name: str) -> Callable[[str, dict], bool]:
    return lambda _path, op: any((p.get("name") or "").lower() == name for p in op.get("parameters", []))


CAVEATS: list[tuple[str, Callable[[str, dict], bool], str]] = [
    ("*", lambda _p, op: _has_time_param(op),
     "Time parameters are epoch MILLISECONDS. Some descriptions say microseconds, but the live server "
     "rejects µs values (START_TIME_GREATER_THAN_CURRENT_TIME)."),
    ("GET", _has_param("startindex"),
     "Paging: startindex is a 0-based record offset (not a page number); pair it with pagesize. "
     "Pass totalcountrequired=true to get totalCount."),
    ("GET", _has_param("fields"),
     "fields=[...] fetches only those fields. A field that doesn't support selective fetch fails the "
     "whole call with SELECTIVE_FETCH_OR_UPDATE_NOT_SUPPORTED_FOR_FIELD: drop it and retry."),
    ("GET", lambda p, _op: p.startswith("/deviceconfiguration/devicetemplates"),
     "Device templates are about 100 KB each because they carry every AP model's radio settings. "
     "Pass modelspecific=false and/or fields=[...]; unfiltered lists exceed the response size limit."),
    ("GET", lambda p, _op: p.startswith("/deviceconfiguration/ssidprofiles") or "radius" in p.lower(),
     "Passphrases and RADIUS secrets come back as ***REDACTED***. Never PUT a record you read back "
     "unchanged: remove the masked fields or supply the real values (bodies containing the "
     "placeholder are refused)."),
    ("POST", lambda p, _op: p == "/locations",
     "POST /locations takes the PARENT folder ({type: folderlocation, id: {type: locallocationid, id}}) "
     "with the new location under children, and echoes the whole parent back. "
     "Prefer cvcue_create_location, which returns the new id."),
    ("DELETE", lambda p, _op: p == "/locations",
     "DELETE /locations takes a JSON body {type: locallocationid, id} and also deletes every child "
     "location. Prefer cvcue_delete_location."),
    ("*", lambda p, _op: p.startswith("/manageddevices/aps") and p.endswith("/reboot"),
     "Rebooting disconnects every client on the AP. Prefer cvcue_reboot_aps (takes a list of MACs)."),
    ("*", lambda p, _op: "{macaddress}" in p,
     "MAC addresses are upper-case and colon-separated (AA:BB:CC:DD:EE:FF)."),
]


def caveats_for(method: str, path: str, op: dict) -> list[str]:
    m = method.upper()
    return [text for methods, match, text in CAVEATS if methods in ("*", m) and match(path, op)]
