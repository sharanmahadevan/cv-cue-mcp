---
title: Curated tools and API discovery
description: Why CV-CUE MCP exposes 38 tools instead of 613, and how Claude finds and calls any CV-CUE endpoint.
---

The CV-CUE REST API has **613 operations across 24 modules**. Exposing one MCP tool per
operation would swamp the model: the tool list alone would fill much of the context window, and
no model can pick reliably from hundreds of similar names.

CV-CUE MCP splits the work in two.

## Curated tools for everyday questions

30 tools cover what people ask most: APs, clients, SSIDs, locations, events, WIPS and
troubleshooting. They do more than pass through one API call:

- **Rollups.** `cvcue_ap_health_summary` pages through every AP and returns counts by model,
  firmware and status, plus the offline and problem APs, instead of hundreds of raw records.
- **One-shot troubleshooting.** `cvcue_troubleshoot_client` combines the client record,
  association history, connection logs, failure events and CV-CUE's inferences in one call.
- **Cleaned-up output.** Location IDs are flattened from `{"type":"locallocationid","id":5}` to
  `5`, timestamps become ISO-8601, and empty fields are dropped.
- **Safety.** Write tools check that writes are enabled, go through
  [confirm before write](/cv-cue-mcp/guides/writes/#confirm-before-write) when it's on, and
  destructive ones also require `confirm=true`.

## Four discovery tools for everything else

For device templates, policies, RF settings, reports, packet captures and the rest, Claude uses
the API the way you would with the docs open:

| Step | Tool | What it does |
|---|---|---|
| 1 | `cvcue_api_modules` | Lists the 24 modules with operation counts |
| 2 | `cvcue_api_search` | Finds endpoints by keyword, optionally by module and HTTP method |
| 3 | `cvcue_api_schema` | Shows an endpoint's parameters, request body and response schema |
| 4 | `cvcue_api_execute` | Calls the endpoint with your connection |

Steps 1–3 read a copy of Arista's published OpenAPI spec bundled with the server, so they're
instant and don't touch your CV-CUE account. Only step 4 calls the API.

### Caveats and notes

The spec doesn't always match how the live API behaves. `cvcue_api_schema` therefore returns two
extra lists with every endpoint:

- **`caveats`**: quirks verified against a live CV-CUE server and shipped with CV-CUE MCP. For
  example, time parameters are epoch milliseconds even where the spec says microseconds; device
  templates need `modelspecific=false` to stay a manageable size; and `startindex` is a record
  offset, not a page number.
- **`your_notes`**: quirks Claude found and saved for your account with
  `cvcue_save_endpoint_note`. They're private to you, come back on every later lookup of that
  endpoint, and can be removed with `cvcue_delete_endpoint_note`.

Claude is told to save only facts it proved against the live API, never guesses, secrets or
customer data. Notes are limited to 500 characters, 10 per endpoint and 300 per account. Notes
need an account; with a raw API key there's nowhere to keep them. On a local server they're kept
in `~/.cvcue-mcp/notes.json`.

### Guard rails on `cvcue_api_execute`

- Anything other than GET is refused unless writes are enabled for the connection, and is
  previewed for your OK first when confirm before write is on.
- Write bodies that contain the `***REDACTED***` placeholder are refused, so a read-modify-write
  can't overwrite a real passphrase with the mask.
- Responses over 100,000 characters are refused with a preview of their shape and tips to
  narrow the request (`fields=[…]`, paging, `locationid`, `modelspecific=false`).

## The response envelope

Every tool returns the same shape, so Claude handles errors the same way everywhere:

```json
{ "ok": true, "data": { … }, "message": "" }
{ "ok": false, "data": null, "message": "No managed AP matches 'lobby-3'", "status": 0 }
```
