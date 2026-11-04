---
title: Getting started
description: Create a CV-CUE API key, sign in with Google, save and test a connection, and get your connector URL.
---

You need three things: a CV-CUE API key, a Google account to sign in with, and an MCP client
such as Claude.

## 1. Create a CV-CUE API key

1. Sign in to **Arista Launchpad** (`launchpad.wifi.arista.com`).
2. Go to **Admin → Keys** and create a key.
3. Pick the **narrowest role** that does what you need. A read-only role is a good start; Claude
   can never do more than the key allows.
4. Copy the **key ID** (it looks like `KEY-ATN…`) and the **key value**. Launchpad shows the
   value only once.

:::tip
If your key can reach several CV-CUE customers, note the **customer ID** too. You'll need it
for the connection.
:::

## 2. Sign in

Open the app (for the public instance, <https://cv-cue-mcp.fly.dev>), accept the terms and choose
**Continue with Google**. Your connections belong to that Google account.

## 3. Add a connection

On the dashboard, under **Add a connection**:

| Field | What to enter |
|---|---|
| Name | Anything that tells you which account it is, e.g. `HQ production` |
| Key ID | From Launchpad |
| Key value | From Launchpad. Encrypted on save and never shown again |
| Customer ID | Only for multi-customer keys |
| API base URL | Usually leave empty: the server finds it through Launchpad. If you set it, it must be `https://…wifi.arista.com/wifi/api` (in CV-CUE: **System → Advanced Settings → Base URLs for APIs**) |
| Allow writes | Leave off unless you want Claude to make changes. See [Enabling writes](/cv-cue-mcp/guides/writes/) |

Choose **Save and test**. The server opens a CV-CUE session with the key and shows the result,
for example *Connected as ADMINISTRATOR, CV-CUE 2026.10.23*. If the test fails, see
[Troubleshooting](/cv-cue-mcp/troubleshooting/).

Your first connection becomes the **default**: the one Claude uses. Add more for other CV-CUE
accounts and switch between them; see [Multiple connections](#multiple-connections).

## 4. Copy your connector URL

The top of the dashboard shows your connector URL:

```
https://cv-cue-mcp.fly.dev/mcp
```

It's the same for everyone; signing in is what ties it to your connections. Next:
[connect it to Claude](/cv-cue-mcp/setup/connecting/).

## Multiple connections

You can save as many connections as you like, for example one per customer or one for a lab.

- Claude always uses your **default** connection.
- Change the default on the dashboard (**Make default**), or ask Claude: *"Switch to my Lab
  connection."* It calls `cvcue_use_connection`, and the change applies from the next tool call.
- `cvcue_list_connections` shows Claude which connections you have and which one is in use.
