---
title: Enabling writes
description: How write access works — the server ceiling, the per-connection switch, confirm-before-write and confirm on destructive tools.
---

Everything is read-only by default. A write has to pass every layer:

| Layer | Who controls it | Where |
|---|---|---|
| 1. Server ceiling | The operator | `CVCUE_ENABLE_WRITES=true` |
| 2. Connection switch | You | Dashboard → connection → **Turn writes on** |
| 3. Key role | Your CV-CUE admin | Launchpad → Admin → Keys |
| 4. Confirm before write | You, in the chat | Every write is previewed and waits for your OK (on by default) |
| 5. Confirmation flag | Claude | Destructive tools also require `confirm=true` |

With a raw API key instead of an account, layer 2 is the `X-CVCUE-Enable-Writes: true` header
and layer 4 is `X-CVCUE-Write-Guard: true` (off unless you send it).

## Confirm before write

Confirm before write is a per-connection setting, on by default for new connections. With it on,
no write reaches CV-CUE the first time Claude tries it:

1. Claude calls a write tool, such as `cvcue_reboot_aps` or a `PUT` through `cvcue_api_execute`.
2. The server doesn't send it. It answers `confirm_required` with a **preview**: the action, the
   exact request, and which connection it targets. It also returns a `confirm_token`.
3. Claude shows you the preview and waits for you to say yes.
4. Claude repeats the **identical** call with the `confirm_token`, and only then does it run.

The token is an HMAC over your account, the connection and a canonical fingerprint of the whole
request. So:

- Changing anything about the request (a MAC, a body field, the path) needs a new preview.
- A token for one connection doesn't work on another.
- Tokens expire after 10 minutes. An old token gets you a fresh preview, not a write.

It's a safety net against mistakes, not an access control: a token isn't single-use, and the
key's CV-CUE role is still what limits what can be changed. Turn it off per connection on the
dashboard (**Turn confirm-before-write off**) if you'd rather writes run directly.

On a [local server](/cv-cue-mcp/guides/local/), set `CVCUE_WRITE_GUARD=true` to get the same
behaviour.

## What counts as a write

- Curated tools marked ✎ in the [tool reference](/cv-cue-mcp/reference/tools/):
  `cvcue_create_location`, `cvcue_delete_location`, `cvcue_reboot_aps`,
  `cvcue_disconnect_client`, `cvcue_delete_ssid`.
- Any `cvcue_api_execute` call that isn't a GET.

## Recommendations

- Keep a **read-only connection as your default**, and a separate write-enabled connection you
  switch to deliberately ("Use my HQ-admin connection").
- Give write-enabled connections a key whose role covers only what you intend to change.
- Leave confirm before write on for any connection that can change production.
- Writes can't send a masked secret back: a body containing `***REDACTED***` is refused, so
  editing an SSID through the API won't overwrite its passphrase with the mask.
