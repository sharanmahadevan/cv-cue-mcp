"""
CLI entry point for the Arista CV-CUE MCP server.

Usage:
  # stdio (default — for Claude Desktop / Claude Code)
  cv-cue-mcp

  # HTTP server with this machine's credentials (single user / private network)
  cv-cue-mcp --http --host 127.0.0.1 --port 8000

  # Hosted, multi-tenant: no stored credentials, each caller sends their own key
  cv-cue-mcp --hosted --host 0.0.0.0 --port 8080     (or MCP_TRANSPORT=hosted)

Environment variables:
  CVCUE_BASE_URL         API base URL from CV-CUE → System → Advanced Settings →
                         "Base URLs for APIs" (e.g. https://<server>/wifi/api)
  CVCUE_KEY_ID           API key ID      (cloud — Launchpad → Admin → Keys)
  CVCUE_KEY_VALUE        API key value
  CVCUE_USERNAME         Local username  (on-premises alternative to API keys)
  CVCUE_PASSWORD         Local password
  CVCUE_CID              Customer ID — only if the key can access several customers
  CVCUE_VERIFY_SSL       true/false (default: true) — set false for self-signed on-prem certs
  CVCUE_CREDENTIALS_FILE INI file with a [cvcue] section (default: ~/.cvcue/credentials)
  CVCUE_OPENAPI_SPEC     Override the bundled OpenAPI spec path
  CVCUE_ENABLE_WRITES    true/false — allow mutating API calls (default: false)
  LOG_LEVEL              DEBUG / INFO / WARNING (default: INFO)
"""

from __future__ import annotations

import argparse
import logging
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cv-cue-mcp", description="Arista CV-CUE MCP server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio")
    parser.add_argument(
        "--hosted",
        action="store_true",
        help="Run as a public multi-tenant HTTP server: callers bring their own CV-CUE API key",
    )
    parser.add_argument("--host", default=None, help="HTTP bind host (default: 127.0.0.1, hosted: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="HTTP bind port (default: 8000, or $PORT)")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (overrides LOG_LEVEL env var)",
    )
    return parser.parse_args()


def _run_hosted(args: argparse.Namespace) -> None:
    import os

    logging.basicConfig(
        level=getattr(logging, (args.log_level or os.environ.get("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        import uvicorn
    except ImportError:
        print("ERROR: hosted mode needs uvicorn: pip install 'cv-cue-mcp[http]'", file=sys.stderr)
        sys.exit(1)
    from .hosted import build_app

    class _StripQuery(logging.Filter):
        """Keep OAuth codes and request ids out of access logs: log paths only."""

        def filter(self, record: logging.LogRecord) -> bool:
            if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
                record.args = (*record.args[:2], record.args[2].split("?", 1)[0], *record.args[3:])
            return True

    logging.getLogger("uvicorn.access").addFilter(_StripQuery())
    uvicorn.run(
        build_app(),
        host=args.host or os.environ.get("MCP_HTTP_HOST", "0.0.0.0"),
        port=args.port or int(os.environ.get("PORT") or os.environ.get("MCP_HTTP_PORT") or 8080),
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="info",
    )


def main() -> None:
    args = _parse_args()

    import os

    if args.hosted or os.environ.get("MCP_TRANSPORT", "").lower() == "hosted":
        _run_hosted(args)
        return

    from .config import load_config

    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, args.log_level or cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.http:
        cfg.transport = "http"
        cfg.http_host = args.host or cfg.http_host
        cfg.http_port = args.port or cfg.http_port

    from .server import create_server

    mcp = create_server(cfg)

    if cfg.transport == "http":
        try:
            import uvicorn  # noqa: F401
        except ImportError:
            print(
                "ERROR: uvicorn is required for HTTP mode.\n"
                "Install it with: pip install 'cv-cue-mcp[http]'",
                file=sys.stderr,
            )
            sys.exit(1)
        mcp.settings.host = cfg.http_host
        mcp.settings.port = cfg.http_port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
