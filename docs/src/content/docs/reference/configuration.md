---
title: Headers and configuration
description: Request headers for bring-your-own-key callers, and every environment variable for operators and local users.
---

## Request headers (bring your own key)

Only needed when you call `/mcp` with a raw API key instead of signing in. See
[Bring your own key](/cv-cue-mcp/setup/connecting/#bring-your-own-key).

| Header | Purpose |
|---|---|
| `Authorization: Bearer <key_id>:<key_value>` | Your CV-CUE API key |
| `X-CVCUE-Key-Id`, `X-CVCUE-Key-Value` | Same, as two headers |
| `X-CVCUE-Base-URL` | API base URL; must be `https://` on an allowed host. Found through Launchpad when omitted |
| `X-CVCUE-CID` | Customer ID for multi-customer keys |
| `X-CVCUE-Enable-Writes` | `true` to opt in to writes, if the server allows them |
| `X-CVCUE-Write-Guard` | `true` to preview every write and require a confirmation token |

## Hosted server (operators)

Set these on your deployment. Secrets go in `fly secrets set`; the rest in `fly.toml` `[env]`.

| Variable | Default | Purpose |
|---|---|---|
| `CVCUE_PUBLIC_URL` | **required** | Public origin, e.g. `https://cv-cue-mcp.fly.dev`. Used as the OAuth issuer and in redirect URLs |
| `CVCUE_MASTER_KEY` | **required, secret** | 32-byte base64url key that encrypts stored API keys. **Back it up**: if it's lost, saved keys can't be decrypted |
| `CVCUE_SESSION_SECRET` | **required, secret** | Signs browser session cookies. Changing it signs everyone out |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | secret | Google OAuth client for sign-in |
| `CVCUE_DB_PATH` | `/data/cvcue.db` | SQLite file on the volume |
| `CVCUE_ENABLE_WRITES` | `false` | Server-wide ceiling. When `false`, every connection is read-only |
| `CVCUE_ALLOWED_HOST_SUFFIXES` | `.wifi.arista.com` | Hosts a connection or `X-CVCUE-Base-URL` may point at |
| `CVCUE_REDACT_SECRETS` | `true` | Mask passphrases and secrets in tool output |
| `CVCUE_MAX_RESPONSE_CHARS` | `100000` | Largest `cvcue_api_execute` response returned |
| `CVCUE_REGISTER_PER_MINUTE` | `5` | OAuth client registrations allowed per IP per minute |
| `CVCUE_POOL_MAX` | `256` | Cached CV-CUE sessions |
| `CVCUE_POOL_IDLE_TTL` | `900` | Seconds before an idle session is logged out |
| `CVCUE_DEV_LOGIN` | `false` | Password-less dev sign-in. Refused unless `CVCUE_PUBLIC_URL` is localhost |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |

## Local server

For running on your own machine with your own key. See [Run it locally](/cv-cue-mcp/guides/local/).

| Variable | Purpose |
|---|---|
| `CVCUE_KEY_ID`, `CVCUE_KEY_VALUE` | API key from Launchpad → Admin → Keys |
| `CVCUE_BASE_URL` | API base URL; optional with an API key |
| `CVCUE_USERNAME`, `CVCUE_PASSWORD` | On-premises CV-CUE local user, instead of a key |
| `CVCUE_CID` | Customer ID for multi-customer keys |
| `CVCUE_ENABLE_WRITES` | `true` to allow writes |
| `CVCUE_WRITE_GUARD` | `true` to preview every write and require a confirmation token |
| `CVCUE_NOTES_PATH` | Where endpoint notes are kept (default `~/.cvcue-mcp/notes.json`) |
| `CVCUE_VERIFY_SSL` | `false` for on-prem servers with self-signed certificates |
| `CVCUE_ENV_FILE` | `.env` file to load |
| `CVCUE_CREDENTIALS_FILE` | INI file with a `[cvcue]` section (default `~/.cvcue/credentials`) |
| `CVCUE_OPENAPI_SPEC` | Use a different OpenAPI spec than the bundled one |

Precedence: Docker secrets (`/run/secrets/cvcue_<field>`), then environment and `.env`, then the
INI file.

## Endpoints

| Path | Purpose |
|---|---|
| `POST /mcp` | MCP over streamable HTTP (stateless, JSON responses) |
| `GET /` | Landing and sign-in page |
| `GET /dashboard` | Connections, connector URL, connected apps |
| `GET /consent` | OAuth approval page |
| `/register`, `/authorize`, `/token`, `/revoke` | OAuth 2.1 endpoints |
| `/.well-known/oauth-authorization-server` | Authorization server metadata |
| `/.well-known/oauth-protected-resource/mcp` | Protected resource metadata |
| `GET /healthz` | Health check |
