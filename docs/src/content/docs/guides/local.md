---
title: Run it locally
description: Run CV-CUE MCP on your own machine over stdio with your own API key — no sign-in, no server.
---

If it's just you, you don't need the hosted app. Run the server locally over stdio with your key
in a `.env` file.

## Install

```bash
git clone https://github.com/sharanmahadevan/cv-cue-mcp && cd cv-cue-mcp
python3.12 -m venv .venv
.venv/bin/pip install .
cp .env.example .env      # then fill in CVCUE_KEY_ID and CVCUE_KEY_VALUE
```

## Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cv-cue": {
      "command": "/path/to/cv-cue-mcp/.venv/bin/cv-cue-mcp",
      "env": { "CVCUE_ENV_FILE": "/path/to/cv-cue-mcp/.env" }
    }
  }
}
```

## Claude Code

```bash
claude mcp add cv-cue -e CVCUE_ENV_FILE=/path/to/cv-cue-mcp/.env -- /path/to/cv-cue-mcp/.venv/bin/cv-cue-mcp
```

## On-premises CV-CUE

Use a local CV-CUE user instead of an API key:

```bash
CVCUE_BASE_URL=https://cvcue.example.internal/wifi/api
CVCUE_USERNAME=api-user
CVCUE_PASSWORD=...
CVCUE_VERIFY_SSL=false     # only for self-signed certificates
```

## Local HTTP

```bash
cv-cue-mcp --http --port 8000
```

This serves `/mcp` with **your** credentials and **no authentication**. Keep it on `127.0.0.1`.
To share a server, use the hosted mode (`--hosted`) instead.

## Running the hosted app locally

For development, the full sign-in app runs locally with a password-less dev login:

```bash
CVCUE_PUBLIC_URL=http://localhost:8765 \
CVCUE_MASTER_KEY=$(python3 -c 'import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))') \
CVCUE_SESSION_SECRET=dev CVCUE_DB_PATH=./dev.db CVCUE_DEV_LOGIN=true \
cv-cue-mcp --hosted --host 127.0.0.1 --port 8765
```

`CVCUE_DEV_LOGIN` is refused unless the public URL is localhost.

:::note[macOS]
Files under `~/Desktop` can get the `hidden` flag, which makes Python 3.12+ skip editable-install
`.pth` files. If `pip install -e .` leaves the package unimportable, use `pip install .` and
reinstall after changes.
:::
