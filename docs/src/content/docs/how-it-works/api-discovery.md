---
title: Curated tools and API discovery
description: Why CV-CUE MCP exposes 36 tools instead of 613, and how Claude finds and calls any CV-CUE endpoint.
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
- **Safety.** Write tools check that writes are enabled, and destructive ones also require
  `confirm=true`.

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

### Guard rails on `cvcue_api_execute`

- Anything other than GET is refused unless writes are enabled for the connection.
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
