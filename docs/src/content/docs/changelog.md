---
title: What's new
description: Changes to CV-CUE MCP.
---

## November 2026

### Sign-in app and Claude custom connector

- Sign in with Google and save CV-CUE API keys as **connections**, encrypted at rest.
- Connect Claude with just the URL: OAuth 2.1 with dynamic client registration and PKCE, with
  a consent page that names the connection Claude will use.
- Several connections per account; switch from the dashboard or by asking Claude
  (`cvcue_list_connections`, `cvcue_use_connection`).
- Writes switched on per connection, under a server-wide ceiling.
- *Connected apps* on the dashboard, with one-click disconnect.
- These docs.

### Hosted endpoint

- Public bring-your-own-key endpoint at `cv-cue-mcp.fly.dev/mcp`.
- Passphrases and secrets masked in tool output; write bodies containing the mask refused.
- `cvcue_api_execute` refuses responses over 100,000 characters and shows their shape.
- `cvcue_create_location` returns the new location's ID.

### Initial release

- 30 curated tools and 4 discovery tools covering all 613 CV-CUE API operations.
