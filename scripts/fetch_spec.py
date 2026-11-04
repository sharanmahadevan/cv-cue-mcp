#!/usr/bin/env python3
"""
Download the CV-CUE OpenAPI specs from the public Arista API portal and merge the
latest version of every module into one OpenAPI 3 document.

The portal (https://apihelp.wifi.arista.com/api/wm) publishes one spec file per
module *and* version. Each file carries the full shared `components` block, so
we keep one copy of components and union the `paths` from the newest version of
each module. Every operation is tagged with its module name and annotated with
`x-module-version` so the client can send the matching `Version` header.

Usage:
    python scripts/fetch_spec.py                       # writes src/cvcue_mcp/spec/cvcue_openapi.json
    python scripts/fetch_spec.py --out /tmp/spec.json
    python scripts/fetch_spec.py --from-dir ./specs    # merge already-downloaded files
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

PORTAL = "https://apihelp.wifi.arista.com/data/wm"
METHODS = ("get", "post", "put", "patch", "delete")
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "src" / "cvcue_mcp" / "spec" / "cvcue_openapi.json"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "cv-cue-mcp-spec-fetcher"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https URL
        return json.load(resp)


def latest_modules(root: dict) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for m in root["info"]["x-MODULES"]:
        if m.get("name") == "UNKNOWN_MODULE":
            continue
        cur = latest.get(m["module"])
        if cur is None or int(m["version"]) > int(cur["version"]):
            latest[m["module"]] = m
    return latest


def merge(root: dict, module_specs: dict[str, tuple[dict, dict]]) -> dict:
    merged: dict = {
        "openapi": root.get("openapi", "3.0.1"),
        "info": {
            "title": root["info"].get("title", "CV-CUE Web API"),
            "version": root["info"].get("version", ""),
            "description": root["info"].get("description", ""),
            "x-module-versions": {},
        },
        "tags": [],
        "paths": {},
        "components": {},
    }
    for module, (meta, spec) in sorted(module_specs.items()):
        merged["info"]["x-module-versions"][module] = int(meta["version"])
        merged["tags"].append({"name": module, "description": meta.get("name", module)})
        if not merged["components"]:
            merged["components"] = spec.get("components", {})
        for path, item in spec.get("paths", {}).items():
            if path in merged["paths"]:
                print(f"warning: duplicate path {path} in {module}; keeping first", file=sys.stderr)
                continue
            for method, op in item.items():
                if method in METHODS and isinstance(op, dict):
                    op["tags"] = [module]
                    op["x-module-version"] = int(meta["version"])
            merged["paths"][path] = item
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--from-dir", type=Path, help="Directory with already-downloaded wm-openapi-*.json files")
    args = ap.parse_args()

    if args.from_dir:
        root = json.loads((args.from_dir / "wm-openapi-root.json").read_text())
    else:
        root = _get_json(f"{PORTAL}/wm-openapi-root.json")

    specs: dict[str, tuple[dict, dict]] = {}
    for module, meta in latest_modules(root).items():
        if args.from_dir and (args.from_dir / meta["fileName"]).exists():
            spec = json.loads((args.from_dir / meta["fileName"]).read_text())
        else:
            print(f"fetching {meta['fileName']}", file=sys.stderr)
            spec = _get_json(f"{PORTAL}/{meta['fileName']}")
        specs[module] = (meta, spec)

    merged = merge(root, specs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, separators=(",", ":")))
    ops = sum(1 for item in merged["paths"].values() for m in item if m in METHODS)
    print(f"wrote {args.out} — {len(specs)} modules, {len(merged['paths'])} paths, {ops} operations", file=sys.stderr)


if __name__ == "__main__":
    main()
