---
title: CV-CUE API notes
description: Quirks of the CV-CUE REST API that matter when calling it through cvcue_api_execute.
---

Things worth knowing when Claude (or you) call the CV-CUE API directly:

- **Paging.** `startindex` is a 0-based record offset and `pagesize` the page length. Add
  `totalcountrequired=true` to get `totalCount`.
- **Scoping.** Most endpoints take `locationid` and return data for that location's whole subtree.
  Location IDs come back as `{"type":"locallocationid","id":N}`; the curated tools flatten them to
  `N`.
- **Time is in milliseconds.** `fromtime` / `totime` are epoch milliseconds. Some spec text says
  microseconds, but the live server rejects µs values.
- **Module versions.** Each module has its own API version, chosen with the `Version` header. The
  server uses its latest when it's omitted; `cvcue_api_execute` takes `version=` to pin one.
- **Creating locations.** `POST /locations` takes the *parent* folder with the new location under
  `children`, and echoes the whole parent back. `cvcue_create_location` does this for you and
  returns just the new location's ID.
- **Deleting locations** also deletes every child location.
- **SSID profiles in use can't be deleted.** Check
  `GET /deviceconfiguration/ssidprofiles/{templateid}/references` first.
- **Sessions.** CV-CUE is session based (`POST /session` returns a `JSESSIONID` cookie). The
  server logs in on first use, re-authenticates on 401, and logs out when a session is evicted.
- **Finding your server.** With an API key and no base URL, the server asks Launchpad which CV-CUE
  (Wireless Manager) server your key belongs to.

The bundled spec comes from Arista's public API portal at
<https://apihelp.wifi.arista.com/api/wm>. Maintainers refresh it with
`python scripts/fetch_spec.py`.
