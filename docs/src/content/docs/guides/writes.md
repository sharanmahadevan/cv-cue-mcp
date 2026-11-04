---
title: Enabling writes
description: How write access works — the server ceiling, the per-connection switch, and confirm on destructive tools.
---

Everything is read-only by default. A write has to pass every layer:

| Layer | Who controls it | Where |
|---|---|---|
| 1. Server ceiling | The operator | `CVCUE_ENABLE_WRITES=true` |
| 2. Connection switch | You | Dashboard → connection → **Turn writes on** |
| 3. Key role | Your CV-CUE admin | Launchpad → Admin → Keys |
| 4. Confirmation | You, in the chat | Destructive tools require `confirm=true` |

With a raw API key instead of an account, layer 2 is the `X-CVCUE-Enable-Writes: true` header.

## What counts as a write

- Curated tools marked ✎ in the [tool reference](/cv-cue-mcp/reference/tools/):
  `cvcue_create_location`, `cvcue_delete_location`, `cvcue_reboot_aps`,
  `cvcue_disconnect_client`, `cvcue_delete_ssid`.
- Any `cvcue_api_execute` call that isn't a GET.

## Recommendations

- Keep a **read-only connection as your default**, and a separate write-enabled connection you
  switch to deliberately ("Use my HQ-admin connection").
- Give write-enabled connections a key whose role covers only what you intend to change.
- Ask Claude to show you the request before it runs it. Destructive tools already refuse to run
  without `confirm=true`.
- Writes can't send a masked secret back: a body containing `***REDACTED***` is refused, so
  editing an SSID through the API won't overwrite its passphrase with the mask.
