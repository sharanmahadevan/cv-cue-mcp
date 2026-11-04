"""
Credential and server configuration loading.

Priority order for CV-CUE credentials:
  1. Docker secrets      (/run/secrets/cvcue_*)
  2. Environment vars    (CVCUE_BASE_URL, CVCUE_KEY_ID, ...)
  3. INI file            (~/.cvcue/credentials or CVCUE_CREDENTIALS_FILE, section [cvcue])

Two authentication modes are supported:
  • API key   (cloud):        key_id + key_value          → type "apikeycredentials"
  • Password  (on-premises):  username + password         → type "usernamepasswordcredentials"
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_SECRETS_DIR = Path("/run/secrets")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHPAD_URL = "https://launchpad.wifi.arista.com/api/v2"
_DEFAULT_INI = Path.home() / ".cvcue" / "credentials"
BUNDLED_SPEC = Path(__file__).resolve().parent / "spec" / "cvcue_openapi.json"

_FIELDS = ("base_url", "key_id", "key_value", "username", "password", "cid", "verify_ssl")


@dataclass
class CvcueCredentials:
    base_url: str
    key_id: str = ""
    key_value: str = ""
    username: str = ""
    password: str = ""
    cid: str = ""                 # customer ID, only for multi-customer keys
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        self.base_url = self.base_url.strip().rstrip("/")

    @property
    def auth_type(self) -> str:
        return "apikeycredentials" if self.key_id else "usernamepasswordcredentials"

    def session_body(self, timeout: int = 3600) -> dict:
        """Request body for POST /session."""
        if self.key_id:
            return {
                "type": "apikeycredentials",
                "keyId": self.key_id,
                "keyValue": self.key_value,
                "clientIdentifier": "cv-cue-mcp",
                "timeout": timeout,
            }
        return {
            "type": "usernamepasswordcredentials",
            "username": self.username,
            "password": self.password,
            "timeout": timeout,
        }

    def is_complete(self) -> bool:
        if self.key_id and self.key_value:
            return True          # base_url may be auto-discovered via Launchpad
        return bool(self.base_url and self.username and self.password)


@dataclass
class ServerConfig:
    credentials: CvcueCredentials
    log_level: str = "INFO"
    transport: str = "stdio"        # "stdio" or "http"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    enable_writes: bool = False     # allow mutating API calls
    openapi_spec_path: str = str(BUNDLED_SPEC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dotenv(paths: list[Path] | None = None) -> None:
    """
    Minimal .env loader (no dependency). Existing environment variables win.
    Looks at CVCUE_ENV_FILE, then ./.env, then the project-root .env.
    """
    candidates = paths or [
        Path(p).expanduser() for p in [os.environ.get("CVCUE_ENV_FILE", "")] if p
    ] + [Path.cwd() / ".env", _PROJECT_ROOT / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip().removeprefix("export ").strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            os.environ.setdefault(key, val)
        log.debug("Loaded environment from %s", path)
        return


def _truthy(val: str | None, default: bool = False) -> bool:
    if val is None or not str(val).strip():
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _build(values: dict[str, str | None], source: str) -> CvcueCredentials | None:
    creds = CvcueCredentials(
        base_url=values.get("base_url") or "",
        key_id=(values.get("key_id") or "").strip(),
        key_value=(values.get("key_value") or "").strip(),
        username=(values.get("username") or "").strip(),
        password=values.get("password") or "",
        cid=(values.get("cid") or "").strip(),
        verify_ssl=_truthy(values.get("verify_ssl"), default=True),
    )
    if not creds.is_complete():
        return None
    log.info("Loaded CV-CUE credentials from %s (%s)", source, creds.auth_type)
    return creds


def _read_secret(name: str) -> str | None:
    try:
        return (_SECRETS_DIR / name).read_text().strip() or None
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("Could not read secret %s: %s", name, exc)
        return None


def _load_from_docker_secrets() -> CvcueCredentials | None:
    return _build({f: _read_secret(f"cvcue_{f}") for f in _FIELDS}, "Docker secrets")


def _load_from_env() -> CvcueCredentials | None:
    return _build({f: os.environ.get(f"CVCUE_{f.upper()}") for f in _FIELDS}, "environment")


def _load_from_ini(path: Path | None = None) -> CvcueCredentials | None:
    ini_path = path or Path(os.environ.get("CVCUE_CREDENTIALS_FILE", str(_DEFAULT_INI))).expanduser()
    if not ini_path.exists():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini_path)
    if "cvcue" not in parser:
        log.warning("INI file %s has no [cvcue] section", ini_path)
        return None
    section = parser["cvcue"]
    return _build({f: section.get(f) for f in _FIELDS}, str(ini_path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config() -> ServerConfig:
    """Load server configuration. Raises SystemExit(1) if no credentials are found."""
    load_dotenv()
    creds = _load_from_docker_secrets() or _load_from_env() or _load_from_ini()
    if creds is None:
        log.error(
            "No CV-CUE credentials found. Provide CVCUE_KEY_ID + CVCUE_KEY_VALUE (cloud; base URL\n"
            "  is auto-discovered if CVCUE_BASE_URL is unset) or CVCUE_BASE_URL + CVCUE_USERNAME +\n"
            "  CVCUE_PASSWORD (on-prem) via a .env file, environment variables, Docker secrets\n"
            "  (/run/secrets/cvcue_*), or an INI file\n"
            "(~/.cvcue/credentials or CVCUE_CREDENTIALS_FILE, section [cvcue])."
        )
        raise SystemExit(1)

    return ServerConfig(
        credentials=creds,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        transport=os.environ.get("MCP_TRANSPORT", "stdio").lower(),
        http_host=os.environ.get("MCP_HTTP_HOST", "127.0.0.1"),
        http_port=int(os.environ.get("MCP_HTTP_PORT", "8000")),
        enable_writes=_truthy(os.environ.get("CVCUE_ENABLE_WRITES"), default=False),
        openapi_spec_path=os.environ.get("CVCUE_OPENAPI_SPEC") or str(BUNDLED_SPEC),
    )
