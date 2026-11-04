---
title: Connecting clients
description: Add CV-CUE MCP to Claude as a custom connector, to Claude Code, or to any MCP client, or use your API key directly.
---

The connector URL is `https://cv-cue-mcp.fly.dev/mcp` (or your own deployment's `/mcp`). MCP
clients that support OAuth discover the sign-in flow on their own: you add the URL, approve the
request on the CV-CUE MCP page that opens, and you're connected.

## Claude (web and desktop)

1. Save at least one connection first ([Getting started](/cv-cue-mcp/setup/getting-started/)).
2. In Claude, open **Settings → Connectors** and choose **Add custom connector**.
3. Name it **CV-CUE**, paste the connector URL and choose **Add**.
4. Choose **Connect**. A CV-CUE MCP page opens; sign in if asked, check the details and choose
   **Allow**.
5. Back in Claude, enable the connector in a chat from the tools menu.

The approval page shows which connection Claude will use and whether writes are on.

:::note
On Team and Enterprise plans an owner may need to add the custom connector for the organisation
first.
:::

## Claude Code

```bash
claude mcp add --transport http cv-cue https://cv-cue-mcp.fly.dev/mcp
```

Then run `/mcp` in Claude Code, pick **cv-cue** and choose **Authenticate**. Your browser opens
the approval page; after **Allow**, Claude Code stores the token and refreshes it automatically.

## Other MCP clients

Any client that supports the MCP authorization spec (OAuth 2.1 with dynamic client registration
and PKCE) works the same way: give it the connector URL. The server publishes its metadata at:

- `/.well-known/oauth-protected-resource/mcp`
- `/.well-known/oauth-authorization-server`

## Bring your own key

You can skip the account entirely and send a CV-CUE API key on every request. Nothing is stored
on the server; the key lives in your client's config.

```
Authorization: Bearer <key_id>:<key_value>
```

| Header | Required | Purpose |
|---|---|---|
| `Authorization: Bearer <key_id>:<key_value>` | yes* | Your CV-CUE API key |
| `X-CVCUE-Key-Id` + `X-CVCUE-Key-Value` | yes* | Alternative to the bearer header |
| `X-CVCUE-Base-URL` | no | Your API base URL; found through Launchpad when omitted. Must be `https://…wifi.arista.com` |
| `X-CVCUE-CID` | no | Customer ID for multi-customer keys |
| `X-CVCUE-Enable-Writes: true` | no | Opt in to writes (only if the server allows writes) |

\* one of the two forms.

Claude Code:

```bash
claude mcp add --transport http cv-cue https://cv-cue-mcp.fly.dev/mcp \
  --header "Authorization: Bearer $CVCUE_KEY_ID:$CVCUE_KEY_VALUE"
```

:::caution
Make sure both variables are set first. If they're empty, the header becomes `Bearer :` and
every call fails with 401. `claude mcp add` also prints the headers it saved, so redirect its
output if others can see your terminal.
:::

Claude Desktop through [`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "cv-cue": {
      "command": "npx",
      "args": ["mcp-remote", "https://cv-cue-mcp.fly.dev/mcp", "--header", "Authorization:${CVCUE_AUTH}"],
      "env": { "CVCUE_AUTH": "Bearer <key_id>:<key_value>" }
    }
  }
}
```

The connection tools (`cvcue_list_connections`, `cvcue_use_connection`) don't apply in this mode.
