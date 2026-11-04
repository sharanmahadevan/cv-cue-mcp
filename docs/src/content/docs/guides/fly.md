---
title: Self-host on Fly.io
description: Run your own CV-CUE MCP with Google sign-in on Fly.io — Google OAuth client, secrets, volume, deploy.
---

Running your own copy means your users' keys live on infrastructure you control, under your own
master key. It takes about 15 minutes.

## What you need

- A [Fly.io](https://fly.io) account and `flyctl`
- A Google Cloud project, for the sign-in OAuth client
- A clone of the repo:

```bash
git clone https://github.com/sharanmahadevan/cv-cue-mcp && cd cv-cue-mcp
```

## 1. Create the Fly app and volume

```bash
fly apps create <your-app>
fly volumes create cvcue_data --size 1 --region sjc --app <your-app>
```

In `fly.toml`, set `app = "<your-app>"` and
`CVCUE_PUBLIC_URL = "https://<your-app>.fly.dev"`.

The database is SQLite on that volume, so run exactly **one** machine.

## 2. Create a Google OAuth client

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), open
   **APIs & Services → OAuth consent screen** and configure it (External, app name, support
   email). Only the basic scopes are needed: `openid`, `email`, `profile`.
2. Go to **Credentials → Create credentials → OAuth client ID**, type **Web application**.
3. Add the authorised redirect URI:
   ```
   https://<your-app>.fly.dev/auth/google/callback
   ```
4. Copy the client ID and secret.

While the consent screen is in *Testing*, only the test users you list can sign in. Publish it
when you're ready for anyone.

## 3. Set the secrets

```bash
fly secrets set --app <your-app> \
  CVCUE_MASTER_KEY="$(python3 -c 'import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))')" \
  CVCUE_SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  GOOGLE_CLIENT_ID="<client-id>" \
  GOOGLE_CLIENT_SECRET="<client-secret>"
```

:::danger[Back up the master key]
`CVCUE_MASTER_KEY` encrypts every saved API key. If you lose it, users must re-enter their keys.
Fly secrets can't be read back, so generate it into your password manager first and set it from
there.
:::

## 4. Deploy

```bash
fly deploy
curl https://<your-app>.fly.dev/healthz
```

Open `https://<your-app>.fly.dev`, sign in, add a connection and connect Claude to
`https://<your-app>.fly.dev/mcp`.

## Allowing writes

Writes are off server-wide by default. To let users turn them on per connection, set
`CVCUE_ENABLE_WRITES = "true"` in `fly.toml` and redeploy. See
[Enabling writes](/cv-cue-mcp/guides/writes/).

## Backups

The volume holds everything: users, encrypted keys and tokens. Fly takes daily volume snapshots;
for your own copy:

```bash
fly ssh console --app <your-app> -C "python -c \"import sqlite3; sqlite3.connect('/data/cvcue.db').backup(sqlite3.connect('/data/backup.db'))\""
fly ssh sftp get /data/backup.db --app <your-app>
```

## Other platforms

The `Dockerfile` runs anywhere. Mount a persistent volume at `/data`, set the variables in
[Headers and configuration](/cv-cue-mcp/reference/configuration/), and expose port 8080.
