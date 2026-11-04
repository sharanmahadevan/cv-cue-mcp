"""
Endpoint notes: short quirks Claude records about a CV-CUE endpoint so they come
back on later cvcue_api_schema lookups.

Local server: a JSON file (CVCUE_NOTES_PATH, default ~/.cvcue-mcp/notes.json).
Hosted app: per-user rows in the database (see hosted.StoreNotes).
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import _shared
from ._shared import NOTE_MAX, NOTE_MIN, NOTES_PER_ENDPOINT, NOTES_TOTAL, err, ok, safe


class FileNotes:
    """Notes in one local JSON file. Fine for a single user on one machine."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except (FileNotFoundError, ValueError):
            return []

    def _save(self, notes: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(notes, indent=1))
        tmp.replace(self.path)

    def list(self, method: str, path: str) -> list[dict[str, Any]]:
        return [n for n in self._load() if n["method"] == method and n["path"] == path]

    def count(self, method: str | None = None, path: str | None = None) -> int:
        return len([n for n in self._load()
                    if method is None or (n["method"] == method and n["path"] == path)])

    def add(self, method: str, path: str, note: str) -> dict[str, Any]:
        with self._lock:
            notes = self._load()
            rec = {"id": "n_" + secrets.token_urlsafe(6), "method": method, "path": path,
                   "note": note, "created_at": time.time()}
            notes.append(rec)
            self._save(notes)
            return rec

    def delete(self, note_id: str) -> bool:
        with self._lock:
            notes = self._load()
            keep = [n for n in notes if n["id"] != note_id]
            if len(keep) == len(notes):
                return False
            self._save(keep)
            return True


def register(mcp: FastMCP, spec_path: str) -> None:
    from .execute import load_spec

    @mcp.tool()
    @safe
    async def cvcue_save_endpoint_note(
        method: Annotated[str, Field(description="HTTP method of the endpoint")],
        path: Annotated[str, Field(description="Path template exactly as in the spec, e.g. '/manageddevices/aps'")],
        note: Annotated[str, Field(description=f"The quirk, {NOTE_MIN}-{NOTE_MAX} characters. No secrets or personal data.")],
    ) -> dict:
        """
        Record a quirk you proved while calling a CV-CUE endpoint (a required parameter the
        spec doesn't mark, a misleading field, an error and its fix) so cvcue_api_schema
        shows it next time. Save only facts you verified against the live API, never guesses,
        secrets or customer data. Limits: 10 notes per endpoint, 300 in total.
        """
        backend = _shared.NOTES()
        if backend is None:
            return err("Endpoint notes need an account: sign in through OAuth (not a raw API key).")
        m, text = method.upper().strip(), " ".join(note.split())
        spec = load_spec(spec_path)
        if spec is not None and m.lower() not in spec.get("paths", {}).get(path, {}):
            return err(f"{m} {path} is not in the API spec. Use the path template from cvcue_api_search.")
        if not NOTE_MIN <= len(text) <= NOTE_MAX:
            return err(f"A note must be {NOTE_MIN}-{NOTE_MAX} characters (got {len(text)}).")
        if any(n["note"].lower() == text.lower() for n in backend.list(m, path)):
            return ok({"duplicate": True}, "That note is already saved for this endpoint.")
        if backend.count(m, path) >= NOTES_PER_ENDPOINT:
            return err(f"{m} {path} already has {NOTES_PER_ENDPOINT} notes. Delete one first.")
        if backend.count() >= NOTES_TOTAL:
            return err(f"You have {NOTES_TOTAL} notes, the maximum. Delete some first.")
        rec = backend.add(m, path, text)
        return ok({"id": rec["id"], "method": m, "path": path, "note": text},
                  f"Saved. cvcue_api_schema will show it for {m} {path}.")

    @mcp.tool()
    @safe
    async def cvcue_delete_endpoint_note(
        note_id: Annotated[str, Field(description="Note id, as shown by cvcue_api_schema")],
    ) -> dict:
        """Delete one of your endpoint notes (for example, one that turned out to be wrong)."""
        backend = _shared.NOTES()
        if backend is None:
            return err("Endpoint notes need an account: sign in through OAuth (not a raw API key).")
        if not backend.delete(note_id.strip()):
            return err(f"No note with id {note_id}.")
        return ok({"deleted": note_id}, "Note deleted.")
