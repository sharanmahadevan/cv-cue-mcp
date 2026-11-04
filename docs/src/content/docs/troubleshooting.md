---
title: Troubleshooting
description: Failed connection tests, connector problems, 401s and 400s, write errors and oversized responses.
---

## The connection test fails

| Message | Cause and fix |
|---|---|
| `Launchpad rejected the API key (HTTP 401)` | Wrong key ID or value, or the key was deleted. Create a new key in Launchpad and add it again |
| `CV-CUE rejected the apikeycredentials credentials` | The key is valid in Launchpad but not on that CV-CUE server. Check the customer ID, or leave the base URL empty |
| `Launchpad lists no CV-CUE Wireless Manager service for this key` | The key isn't attached to a CV-CUE service. Set the base URL explicitly |
| `POST …/session returned 404` | The base URL is missing `/wifi/api`. Copy it from CV-CUE → System → Advanced Settings → Base URLs for APIs |
| `Base URL host '…' is not allowed` | Only `*.wifi.arista.com` is allowed on the public server. On-prem CV-CUE needs a [local server](/cv-cue-mcp/guides/local/) |

## Claude can't connect

- **The approval page never appears.** Pop-ups may be blocked. Allow pop-ups for claude.ai and
  choose **Connect** again.
- **"Request expired".** Approval links last 15 minutes. Start again from Claude.
- **You're asked to add a connection.** You need at least one saved connection before approving.
  Add it, and you'll return to the approval page.
- **The connector shows no tools.** Disconnect it in Claude and connect again; check that the
  connector is enabled in the chat's tools menu.

## 401 Unauthorized

- **OAuth clients:** the token expired and couldn't be refreshed, or you disconnected the app on
  the dashboard. Reconnect from Claude (or `/mcp` → Authenticate in Claude Code).
- **Raw key:** the `Authorization` header must be `Bearer <key_id>:<key_value>`. A header of
  `Bearer :` means your environment variables were empty when you added the server.

## 400 Bad Request

`X-CVCUE-Base-URL` must be `https://` on an allowed host, with no port or credentials.

## "No CV-CUE connection saved"

You deleted every connection after connecting Claude. Add one on the dashboard. You don't need to
reconnect Claude.

## "Write operations are disabled for this connection"

Writes are off for the connection, or the server doesn't allow them. See
[Enabling writes](/cv-cue-mcp/guides/writes/).

## "Request body contains the ***REDACTED*** placeholder"

Claude read a record with masked secrets and tried to write it back. Remove those fields from the
body, or supply the real values.

## Response too large (413)

`cvcue_api_execute` refuses responses over 100,000 characters and shows their shape. Narrow the
call with `fields`, paging, `locationid` or `modelspecific=false`. See [Limits](/cv-cue-mcp/reference/limits/).

## `SELECTIVE_FETCH_OR_UPDATE_NOT_SUPPORTED_FOR_FIELD`

That field can't be used in `fields=[…]` on that endpoint. Drop it and retry.

## The first request is slow

The public instance stops when idle and starts on the next request, which adds a few seconds.
The first call on a connection also opens a CV-CUE session.

## Still stuck?

Open an issue at <https://github.com/sharanmahadevan/cv-cue-mcp/issues> with the tool name and
error message. Never include your key value.
