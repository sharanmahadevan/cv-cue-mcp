---
title: Limits
description: Response sizes, paging, token lifetimes, session caching and request concurrency.
---

| Limit | Value | What happens when you hit it |
|---|---|---|
| `cvcue_api_execute` response size | 100,000 characters | Refused with `status: 413`, the response size, a preview of its shape, and tips to narrow it |
| Page size on list tools | up to 500 records per call | Use `start` / `page_size` to page |
| Rollup tools (health summaries) | up to 10,000 records | Totals are still reported; lists are capped |
| Access token | 1 hour | Your client refreshes it automatically |
| Refresh token | 30 days, rotated on use | Approve the client again |
| Authorization request | 15 minutes | Start the connection again from your client |
| Cached CV-CUE session | 15 minutes idle | A new session opens on the next call |
| Write-guard confirmation token | 10 minutes | A fresh preview is returned instead of the write |
| Endpoint notes | 5–500 characters; 10 per endpoint; 300 per account | Refused with the limit named. Delete notes with `cvcue_delete_endpoint_note` |
| OAuth client registration | 5 per minute per IP | `429` with `Retry-After` |
| Concurrent requests (public instance) | 100 per machine (`hard_limit` in `fly.toml`) | Fly's proxy holds back further requests until capacity frees up |

CV-CUE's own limits still apply on top: API rate limits, your key's role, and session limits on
the CV-CUE server. A 429 from CV-CUE is retried with backoff before it's reported.

## Large responses

Some endpoints return a lot. Device templates are about 100 KB each because they include every
AP model's radio settings. To keep responses manageable:

- `fields=["templateId","templateName"]` fetches only those fields, on endpoints that support
  selective fetch. Unsupported fields fail with `SELECTIVE_FETCH_OR_UPDATE_NOT_SUPPORTED_FOR_FIELD`;
  drop the field and retry.
- `modelspecific=false` on `/deviceconfiguration/devicetemplates` leaves out per-model settings.
- `pagesize` and `startindex` page list endpoints.
- `locationid` scopes a call to one location's subtree.
