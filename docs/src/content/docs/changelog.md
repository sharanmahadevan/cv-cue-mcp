---
title: What's new
description: Changes to CV-CUE MCP.
---

## November 2026

### QA fixes

- `cvcue_create_location` now returns the new id for locations created below a non-root parent
  (CV-CUE echoes the whole tree from the root, so the id used to come back as "not found").
- POST requests (reboot, create, disconnect...) are no longer retried after a server error or a
  dropped connection, so a slow write can't run twice. They are still retried on HTTP 429 or when
  the connection never opened.
- `cvcue_rogue_ap_summary` counts per classification now exclude managed APs, matching
  `cvcue_list_rogue_aps`.
- Documented that floors inherit their parent folder's timezone.

### Workflow prompts, confirm before write, API notes

- Six read-only [workflow prompts](/cv-cue-mcp/reference/prompts/) in Claude's + menu: RF health
  review, client deep-dive, why a client can't connect, site as-built document, rogue AP review
  and configuration audit.
- [Confirm before write](/cv-cue-mcp/guides/writes/#confirm-before-write): every write is
  previewed and runs only after your OK. On by default for new connections; switch it per
  connection on the dashboard. `X-CVCUE-Write-Guard` and `CVCUE_WRITE_GUARD` for raw keys and
  local servers.
- `cvcue_api_schema` returns live-tested [caveats](/cv-cue-mcp/how-it-works/api-discovery/#caveats-and-notes)
  and your saved notes; new `cvcue_save_endpoint_note` and `cvcue_delete_endpoint_note`.
- Stored keys now use a per-record encryption key (HKDF-SHA256 with a random salt); existing keys
  were re-encrypted automatically.
- **Disconnect all apps** on the dashboard, a rate limit on OAuth client registration, and an
  [FAQ](https://cv-cue-mcp.fly.dev/faq).

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
