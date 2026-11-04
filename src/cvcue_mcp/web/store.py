"""
Persistent storage for the hosted sign-in app (SQLite).

What is stored
  users          Google account id + email
  connections    a user's CV-CUE API keys. key_value is AES-256-GCM encrypted under a
                 per-record key derived (HKDF-SHA256, random salt) from CVCUE_MASTER_KEY,
                 and is never returned to the browser or to Claude.
  endpoint_notes API quirks Claude saved for the user (cvcue_save_endpoint_note)
  oauth_clients  MCP clients registered through dynamic client registration
  oauth_codes / oauth_tokens
                 authorization codes and access/refresh tokens, stored only as
                 SHA-256 hashes of the token value.

All methods are synchronous and short; callers run them via asyncio.to_thread.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    google_sub  TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS connections (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    key_id          TEXT NOT NULL,
    key_value_enc   BLOB NOT NULL,
    base_url        TEXT NOT NULL DEFAULT '',
    cid             TEXT NOT NULL DEFAULT '',
    allow_writes    INTEGER NOT NULL DEFAULT 0,
    is_default      INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    last_tested_at  REAL,
    last_test_ok    INTEGER,
    last_test_msg   TEXT
);
CREATE INDEX IF NOT EXISTS connections_user ON connections(user_id);
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id   TEXT PRIMARY KEY,
    info_json   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_requests (
    id          TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    params_json TEXT NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash   TEXT PRIMARY KEY,
    data_json   TEXT NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash  TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,            -- 'access' | 'refresh'
    client_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scopes      TEXT NOT NULL,
    resource    TEXT,
    expires_at  REAL,
    pair_id     TEXT NOT NULL,            -- links an access token to its refresh token
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS oauth_tokens_user ON oauth_tokens(user_id);
CREATE TABLE IF NOT EXISTS endpoint_notes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    note        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS endpoint_notes_user ON endpoint_notes(user_id, method, path);
"""

# Columns added after the first release: (table, column, definition)
MIGRATIONS = [
    ("connections", "write_guard", "INTEGER NOT NULL DEFAULT 1"),
]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(18)


@dataclass
class User:
    id: str
    google_sub: str
    email: str
    name: str | None


@dataclass
class Connection:
    id: str
    user_id: str
    name: str
    key_id: str
    base_url: str
    cid: str
    allow_writes: bool
    write_guard: bool
    is_default: bool
    created_at: float
    last_tested_at: float | None
    last_test_ok: bool | None
    last_test_msg: str | None

    @property
    def key_id_masked(self) -> str:
        k = self.key_id
        return k if len(k) <= 8 else f"{k[:4]}…{k[-4:]}"


class Cipher:
    """
    AES-256-GCM. Each value gets its own key, HKDF-SHA256(master key, random 16-byte salt),
    and a random 96-bit nonce. Envelope v2: 0x02 | salt(16) | nonce(12) | ciphertext+tag.
    v1 values (nonce | ciphertext, encrypted directly with the master key) still decrypt,
    and Store.upgrade_encryption() rewrites them as v2.
    """

    V2 = 2
    _INFO = b"cv-cue-mcp connection key v2"

    def __init__(self, master_key_b64: str) -> None:
        key = base64.urlsafe_b64decode(master_key_b64 + "=" * (-len(master_key_b64) % 4))
        if len(key) != 32:
            raise ValueError("CVCUE_MASTER_KEY must be 32 bytes, base64url-encoded")
        self._master = key
        self._aes_v1 = AESGCM(key)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

    def _derive(self, salt: bytes) -> AESGCM:
        return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=self._INFO).derive(self._master))

    def encrypt(self, plaintext: str, aad: str) -> bytes:
        salt, nonce = os.urandom(16), os.urandom(12)
        return bytes([self.V2]) + salt + nonce + self._derive(salt).encrypt(nonce, plaintext.encode(), aad.encode())

    def decrypt_versioned(self, blob: bytes, aad: str) -> tuple[str, int]:
        blob = bytes(blob)
        if blob[:1] == bytes([self.V2]) and len(blob) > 1 + 16 + 12 + 16:
            salt, nonce, ct = blob[1:17], blob[17:29], blob[29:]
            try:
                return self._derive(salt).decrypt(nonce, ct, aad.encode()).decode(), self.V2
            except InvalidTag:
                pass      # a v1 nonce can start with 0x02 too; fall through
        return self._aes_v1.decrypt(blob[:12], blob[12:], aad.encode()).decode(), 1

    def decrypt(self, blob: bytes, aad: str) -> str:
        return self.decrypt_versioned(blob, aad)[0]


class Store:
    def __init__(self, path: str | Path, cipher: Cipher) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self._lock = threading.Lock()
        self.cipher = cipher

    def upgrade_encryption(self) -> int:
        """Re-encrypt any v1 key values with per-record derived keys. Returns how many changed."""
        changed = 0
        for r in self._q("SELECT id, user_id, key_value_enc FROM connections"):
            aad = f"{r['user_id']}:{r['id']}"
            plain, version = self.cipher.decrypt_versioned(r["key_value_enc"], aad)
            if version != Cipher.V2:
                self._x("UPDATE connections SET key_value_enc = ? WHERE id = ?", (self.cipher.encrypt(plain, aad), r["id"]))
                changed += 1
        return changed

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).rowcount

    # ------------------------------------------------------------------ users

    def upsert_user(self, google_sub: str, email: str, name: str | None) -> User:
        rows = self._q("SELECT * FROM users WHERE google_sub = ?", (google_sub,))
        if rows:
            self._x("UPDATE users SET email = ?, name = ? WHERE google_sub = ?", (email, name, google_sub))
            uid = rows[0]["id"]
        else:
            uid = new_id("u_")
            self._x("INSERT INTO users VALUES (?, ?, ?, ?, ?)", (uid, google_sub, email, name, time.time()))
        return User(uid, google_sub, email, name)

    def get_user(self, user_id: str) -> User | None:
        rows = self._q("SELECT * FROM users WHERE id = ?", (user_id,))
        return User(rows[0]["id"], rows[0]["google_sub"], rows[0]["email"], rows[0]["name"]) if rows else None

    def delete_user(self, user_id: str) -> None:
        self._x("DELETE FROM users WHERE id = ?", (user_id,))

    # ------------------------------------------------------------ connections

    @staticmethod
    def _conn(r: sqlite3.Row) -> Connection:
        return Connection(
            id=r["id"], user_id=r["user_id"], name=r["name"], key_id=r["key_id"], base_url=r["base_url"],
            cid=r["cid"], allow_writes=bool(r["allow_writes"]), write_guard=bool(r["write_guard"]),
            is_default=bool(r["is_default"]),
            created_at=r["created_at"], last_tested_at=r["last_tested_at"],
            last_test_ok=None if r["last_test_ok"] is None else bool(r["last_test_ok"]),
            last_test_msg=r["last_test_msg"],
        )

    def list_connections(self, user_id: str) -> list[Connection]:
        rows = self._q(
            "SELECT * FROM connections WHERE user_id = ? ORDER BY is_default DESC, created_at", (user_id,)
        )
        return [self._conn(r) for r in rows]

    def get_connection(self, user_id: str, conn_id: str) -> Connection | None:
        rows = self._q("SELECT * FROM connections WHERE user_id = ? AND id = ?", (user_id, conn_id))
        return self._conn(rows[0]) if rows else None

    def default_connection(self, user_id: str) -> Connection | None:
        conns = self.list_connections(user_id)
        return next((c for c in conns if c.is_default), conns[0] if conns else None)

    def add_connection(
        self, user_id: str, name: str, key_id: str, key_value: str,
        base_url: str = "", cid: str = "", allow_writes: bool = False,
    ) -> Connection:
        cid_ = new_id("c_")
        first = not self._q("SELECT 1 FROM connections WHERE user_id = ?", (user_id,))
        enc = self.cipher.encrypt(key_value, aad=f"{user_id}:{cid_}")
        self._x(
            "INSERT INTO connections (id, user_id, name, key_id, key_value_enc, base_url, cid, allow_writes,"
            " is_default, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid_, user_id, name, key_id, enc, base_url, cid, int(allow_writes), int(first), time.time()),
        )
        conn = self.get_connection(user_id, cid_)
        assert conn is not None
        return conn

    def key_value(self, conn: Connection) -> str:
        rows = self._q("SELECT key_value_enc FROM connections WHERE id = ? AND user_id = ?", (conn.id, conn.user_id))
        return self.cipher.decrypt(rows[0]["key_value_enc"], aad=f"{conn.user_id}:{conn.id}")

    def set_default(self, user_id: str, conn_id: str) -> bool:
        if not self.get_connection(user_id, conn_id):
            return False
        with self._lock:
            self._db.execute("BEGIN")
            self._db.execute("UPDATE connections SET is_default = 0 WHERE user_id = ?", (user_id,))
            self._db.execute("UPDATE connections SET is_default = 1 WHERE user_id = ? AND id = ?", (user_id, conn_id))
            self._db.execute("COMMIT")
        return True

    def set_writes(self, user_id: str, conn_id: str, allow: bool) -> None:
        self._x("UPDATE connections SET allow_writes = ? WHERE user_id = ? AND id = ?", (int(allow), user_id, conn_id))

    def set_write_guard(self, user_id: str, conn_id: str, on: bool) -> None:
        self._x("UPDATE connections SET write_guard = ? WHERE user_id = ? AND id = ?", (int(on), user_id, conn_id))

    def record_test(self, user_id: str, conn_id: str, ok: bool, msg: str, base_url: str | None = None) -> None:
        self._x(
            "UPDATE connections SET last_tested_at = ?, last_test_ok = ?, last_test_msg = ? WHERE user_id = ? AND id = ?",
            (time.time(), int(ok), msg[:300], user_id, conn_id),
        )

    def delete_connection(self, user_id: str, conn_id: str) -> None:
        was_default = (c := self.get_connection(user_id, conn_id)) is not None and c.is_default
        self._x("DELETE FROM connections WHERE user_id = ? AND id = ?", (user_id, conn_id))
        if was_default and (rest := self.list_connections(user_id)):
            self.set_default(user_id, rest[0].id)

    # --------------------------------------------------------- endpoint notes

    def list_notes(self, user_id: str, method: str, path: str) -> list[dict]:
        rows = self._q("SELECT * FROM endpoint_notes WHERE user_id = ? AND method = ? AND path = ? ORDER BY created_at",
                       (user_id, method, path))
        return [dict(r) for r in rows]

    def count_notes(self, user_id: str, method: str | None = None, path: str | None = None) -> int:
        if method is None:
            return self._q("SELECT COUNT(*) AS n FROM endpoint_notes WHERE user_id = ?", (user_id,))[0]["n"]
        return self._q("SELECT COUNT(*) AS n FROM endpoint_notes WHERE user_id = ? AND method = ? AND path = ?",
                       (user_id, method, path))[0]["n"]

    def add_note(self, user_id: str, method: str, path: str, note: str) -> dict:
        rec = {"id": new_id("n_"), "user_id": user_id, "method": method, "path": path, "note": note,
               "created_at": time.time()}
        self._x("INSERT INTO endpoint_notes VALUES (:id, :user_id, :method, :path, :note, :created_at)", rec)
        return rec

    def delete_note(self, user_id: str, note_id: str) -> bool:
        return self._x("DELETE FROM endpoint_notes WHERE user_id = ? AND id = ?", (user_id, note_id)) > 0

    # ------------------------------------------------------------------ OAuth

    def save_client(self, client_id: str, info: dict) -> None:
        self._x("INSERT OR REPLACE INTO oauth_clients VALUES (?, ?, ?)", (client_id, json.dumps(info), time.time()))

    def get_client(self, client_id: str) -> dict | None:
        rows = self._q("SELECT info_json FROM oauth_clients WHERE client_id = ?", (client_id,))
        return json.loads(rows[0]["info_json"]) if rows else None

    def save_request(self, client_id: str, params: dict, ttl: float = 900) -> str:
        rid = new_id("r_")
        self._x("INSERT INTO oauth_requests VALUES (?, ?, ?, ?)", (rid, client_id, json.dumps(params), time.time() + ttl))
        return rid

    def get_request(self, rid: str) -> tuple[str, dict] | None:
        rows = self._q("SELECT * FROM oauth_requests WHERE id = ? AND expires_at > ?", (rid, time.time()))
        return (rows[0]["client_id"], json.loads(rows[0]["params_json"])) if rows else None

    def delete_request(self, rid: str) -> None:
        self._x("DELETE FROM oauth_requests WHERE id = ?", (rid,))

    def save_code(self, code: str, data: dict) -> None:
        self._x("INSERT INTO oauth_codes VALUES (?, ?, ?)", (token_hash(code), json.dumps(data), data["expires_at"]))

    def get_code(self, code: str) -> dict | None:
        rows = self._q("SELECT data_json FROM oauth_codes WHERE code_hash = ? AND expires_at > ?",
                       (token_hash(code), time.time()))
        return json.loads(rows[0]["data_json"]) if rows else None

    def delete_code(self, code: str) -> None:
        self._x("DELETE FROM oauth_codes WHERE code_hash = ?", (token_hash(code),))

    def save_token(self, token: str, kind: str, client_id: str, user_id: str, scopes: list[str],
                   resource: str | None, expires_at: float | None, pair_id: str) -> None:
        self._x(
            "INSERT INTO oauth_tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (token_hash(token), kind, client_id, user_id, " ".join(scopes), resource, expires_at, pair_id, time.time()),
        )

    def get_token(self, token: str, kind: str) -> sqlite3.Row | None:
        rows = self._q(
            "SELECT * FROM oauth_tokens WHERE token_hash = ? AND kind = ? AND (expires_at IS NULL OR expires_at > ?)",
            (token_hash(token), kind, time.time()),
        )
        return rows[0] if rows else None

    def revoke_pair(self, pair_id: str) -> None:
        self._x("DELETE FROM oauth_tokens WHERE pair_id = ?", (pair_id,))

    def revoke_user_tokens(self, user_id: str) -> int:
        return self._x("DELETE FROM oauth_tokens WHERE user_id = ?", (user_id,))

    def active_grants(self, user_id: str) -> list[dict]:
        rows = self._q(
            "SELECT t.client_id, MIN(t.created_at) AS since, c.info_json FROM oauth_tokens t "
            "LEFT JOIN oauth_clients c ON c.client_id = t.client_id "
            "WHERE t.user_id = ? AND t.kind = 'refresh' AND (t.expires_at IS NULL OR t.expires_at > ?) "
            "GROUP BY t.client_id",
            (user_id, time.time()),
        )
        out = []
        for r in rows:
            info = json.loads(r["info_json"]) if r["info_json"] else {}
            out.append({"client_id": r["client_id"], "client_name": info.get("client_name") or "MCP client",
                        "since": r["since"]})
        return out

    def revoke_client_for_user(self, user_id: str, client_id: str) -> None:
        self._x("DELETE FROM oauth_tokens WHERE user_id = ? AND client_id = ?", (user_id, client_id))

    def purge_expired(self) -> None:
        now = time.time()
        self._x("DELETE FROM oauth_requests WHERE expires_at <= ?", (now,))
        self._x("DELETE FROM oauth_codes WHERE expires_at <= ?", (now,))
        self._x("DELETE FROM oauth_tokens WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
