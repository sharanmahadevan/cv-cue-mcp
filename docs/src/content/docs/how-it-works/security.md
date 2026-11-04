---
title: Security model
description: Where your CV-CUE key lives, how it's encrypted, how tokens work, and what Claude can and cannot see.
---

## Your CV-CUE API key

- **Encrypted at rest.** The key value is encrypted with AES-256-GCM before it's written to the
  database. Each value has a random nonce and is bound to its user and connection, so a value
  copied into another row won't decrypt.
- **Write-only.** After you save it, the key value is never shown again: not on the dashboard,
  not in any API response, not to Claude. The dashboard shows only a masked key ID.
- **Decrypted only in memory**, at the moment the server opens a CV-CUE session for you. The
  session is cached in memory for up to 15 minutes of inactivity, then logged out.
- **Never sent to Claude.** Claude gets an opaque access token for CV-CUE MCP, never your
  CV-CUE key.
- **Deleted when you say so.** Deleting a connection or your account removes it immediately and
  ends any cached session.

The encryption key (`CVCUE_MASTER_KEY`) is a server secret held outside the database.

## What Claude can do

Exactly what your CV-CUE API key's role allows, and no more:

- **Read-only by default.** Writes need to be switched on for the connection (and allowed by the
  server operator). See [Enabling writes](/cv-cue-mcp/guides/writes/).
- **Confirm on destructive actions.** Reboot, disconnect and delete tools also require
  `confirm=true`, which Claude only sends after asking you.
- **Secrets are masked.** Wi-Fi passphrases, RADIUS and CoA secrets and similar fields come back
  as `***REDACTED***`, and write requests containing that placeholder are refused.

## Sign-in and tokens

- **Google sign-in** identifies your account. The server keeps your Google account ID, email and
  name, and nothing else from Google.
- **OAuth 2.1 with PKCE** connects Claude. Claude registers itself, you approve it on the consent
  page, and Claude receives an access token (valid 1 hour) and a refresh token (30 days, rotated
  on each use).
- **Tokens are stored as SHA-256 hashes**, never in plain text.
- **Disconnect any time.** *Connected apps* on the dashboard lists every app you've approved;
  **Disconnect** revokes its tokens immediately.
- **Browser protections.** Session cookies are signed, `HttpOnly`, `SameSite=Lax` and `Secure`.
  Forms carry CSRF tokens, and pages can't be framed.

## Network protections

- The server only talks to CV-CUE hosts under `*.wifi.arista.com` over HTTPS (plus Launchpad to
  find your server). A custom base URL elsewhere is rejected, so the server can't be used to
  reach other hosts.
- TLS certificates are always verified.

## What the server doesn't keep

Your network data. Tool results pass through the server to your MCP client and aren't saved or
logged. Request logs contain paths and status codes, not headers or bodies.

## Bring-your-own-key mode

If you send `Authorization: Bearer <key_id>:<key_value>` instead of signing in, nothing is stored
at all: the key is used for that request and its cached session, then forgotten. It does live in
your MCP client's config file, so protect that file.

## Self-hosting

Everything above applies to your own deployment too, and then you hold the master key. See
[Self-host on Fly.io](/cv-cue-mcp/guides/fly/).
