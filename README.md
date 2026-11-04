# cv-cue-mcp — MCP server for Arista CV-CUE

An [MCP](https://modelcontextprotocol.io) server for **Arista CV-CUE** (CloudVision Cognitive
Unified Edge), Arista's cloud-managed Wi-Fi platform.

- **30 curated tools** for day-to-day work: APs, clients, SSIDs, locations, events, WIPS/rogues,
  troubleshooting, switches
- **4 discovery tools** that open up the **whole CV-CUE REST API** (613 operations across 24
  modules) without registering hundreds of tools
- **6 workflow prompts** in Claude's + menu: RF health review, client deep-dive, can't-connect
  diagnosis, site as-built document, rogue AP review, configuration audit
- **Confirm before write**: writes are previewed and run only after the user's OK
- **API caveats and notes**: live-tested quirks shown with each endpoint's schema, plus notes
  Claude saves as it learns
- Every tool returns the same `{ok, data, message}` envelope
- Secrets (PSK passphrases, RADIUS secrets, …) are **redacted** before they reach the model

📖 **Docs: <https://sharanmahadevan.github.io/cv-cue-mcp/>**

It runs three ways:

| Mode | Who it's for | Credentials |
|---|---|---|
| **Hosted app** (`--hosted`) | Anyone: sign in with Google, save a CV-CUE key, add one URL to Claude | Saved per user, AES-256-GCM encrypted |
| **Bring your own key** (same endpoint) | Clients that can set headers; no account | Sent on each request, never stored |
| **Local** (stdio or `--http`) | You, on your own machine | Your key in `.env` |

> Not affiliated with or endorsed by Arista Networks. "Arista" and "CV-CUE" are trademarks of
> Arista Networks, Inc.

---

## Using the hosted app

1. Create an API key in **Launchpad → Admin → Keys** (narrowest role that works).
2. Sign in at <https://cv-cue-mcp.fly.dev>, add the key as a connection and test it.
3. In Claude: **Settings → Connectors → Add custom connector** →
   `https://cv-cue-mcp.fly.dev/mcp` → **Connect**, then **Allow** on the approval page.

Claude Code: `claude mcp add --transport http cv-cue https://cv-cue-mcp.fly.dev/mcp`, then `/mcp`
→ Authenticate.

Keys are encrypted at rest, decrypted only in memory, never shown again and never sent to Claude.
Everything is read-only unless writes are allowed by the server **and** switched on for the
connection. Details: [Security model](https://sharanmahadevan.github.io/cv-cue-mcp/how-it-works/security/).

**Bring your own key** instead of an account:

```bash
claude mcp add --transport http cv-cue https://cv-cue-mcp.fly.dev/mcp \
  --header "Authorization: Bearer $CVCUE_KEY_ID:$CVCUE_KEY_VALUE" > /dev/null
```

See [Connecting clients](https://sharanmahadevan.github.io/cv-cue-mcp/setup/connecting/) for
optional headers and Claude Desktop via `mcp-remote`.

## Self-hosting

```bash
fly apps create <your-app> && fly volumes create cvcue_data --size 1 --app <your-app>
fly secrets set CVCUE_MASTER_KEY=… CVCUE_SESSION_SECRET=… GOOGLE_CLIENT_ID=… GOOGLE_CLIENT_SECRET=…
fly deploy
```

Full walkthrough, including the Google OAuth client and backing up the master key:
[Self-host on Fly.io](https://sharanmahadevan.github.io/cv-cue-mcp/guides/fly/). All variables:
[Headers and configuration](https://sharanmahadevan.github.io/cv-cue-mcp/reference/configuration/).

---

## Local setup (your own key, on your machine)

```bash
git clone https://github.com/sharanmahadevan/cv-cue-mcp && cd cv-cue-mcp
python3.12 -m venv .venv
.venv/bin/pip install .               # '.[dev]' for tests, '.[http]' for HTTP/hosted modes
cp .env.example .env                  # then fill in your values
```

### Configuration (`.env`, environment variables, Docker secrets, or INI)

| Variable | Purpose |
|---|---|
| `CVCUE_BASE_URL` | API base URL, e.g. `https://awmXXXXX-c4.srv.wifi.arista.com/wifi/api`. In CV-CUE: **System → Advanced Settings → Base URLs for APIs**. Optional with an API key (found through Launchpad). |
| `CVCUE_KEY_ID` / `CVCUE_KEY_VALUE` | API key from **Launchpad → Admin → Keys** (cloud) |
| `CVCUE_USERNAME` / `CVCUE_PASSWORD` | Local user (on-prem alternative to an API key; local mode only) |
| `CVCUE_CID` | Customer ID. Only needed when the key can reach more than one customer. |
| `CVCUE_ENABLE_WRITES` | `true` allows mutating calls. Default `false`. |
| `CVCUE_REDACT_SECRETS` | `false` shows secrets in tool output. Default `true`. |
| `CVCUE_VERIFY_SSL` | `false` for on-prem servers with self-signed certificates |
| `CVCUE_ENV_FILE` | Path to the `.env` file to load. Defaults to `./.env`, then the project root. |
| `CVCUE_CREDENTIALS_FILE` | INI file with a `[cvcue]` section (default `~/.cvcue/credentials`) |
| `CVCUE_OPENAPI_SPEC` | Use a different OpenAPI spec instead of the bundled one |

Precedence: Docker secrets (`/run/secrets/cvcue_<field>`), then environment and `.env`, then the
INI file. Real environment variables override `.env` values.

### Claude Desktop

```json
{
  "mcpServers": {
    "arista-cv-cue": {
      "command": "/path/to/cv-cue-mcp/.venv/bin/cv-cue-mcp",
      "env": { "CVCUE_ENV_FILE": "/path/to/cv-cue-mcp/.env" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add arista-cv-cue -e CVCUE_ENV_FILE=/path/to/cv-cue-mcp/.env -- /path/to/cv-cue-mcp/.venv/bin/cv-cue-mcp
```

### Local HTTP mode

```bash
cv-cue-mcp --http --port 8000     # streamable HTTP at /mcp, using YOUR credentials, no auth
```

This mode has no authentication — keep it on `127.0.0.1` or a private network. To expose a
server publicly, use `--hosted`.

---

## How CV-CUE auth works

CV-CUE uses sessions. `POST /session` with an API key (cloud) or a username and password
(on-prem) returns a `JSESSIONID` cookie, and later calls send that cookie. The client:

- logs in on the first tool call, so the server starts even if CV-CUE is unreachable
- logs in again by itself when the session expires (HTTP 401)
- retries 429/5xx responses
- logs out on shutdown (or when a hosted session is evicted)

If you supply an API key but no base URL, the server asks **Launchpad** for your CV-CUE server
and builds `https://<awm-server>/wifi/api` itself.

## Tools

Full reference with parameters: [Tools](https://sharanmahadevan.github.io/cv-cue-mcp/reference/tools/).

| Area | Tools |
|---|---|
| Session / system | `cvcue_session_info`, `cvcue_server_info` |
| Connections (hosted) | `cvcue_list_connections`, `cvcue_use_connection` |
| Locations | `cvcue_list_locations`, `cvcue_get_location`, `cvcue_create_location`✎, `cvcue_delete_location`✎ |
| Access points | `cvcue_list_aps`, `cvcue_get_ap`, `cvcue_ap_health_summary`, `cvcue_list_radios`, `cvcue_reboot_aps`✎ |
| Clients | `cvcue_list_clients`, `cvcue_find_client`, `cvcue_client_health_summary`, `cvcue_client_association_history`, `cvcue_disconnect_client`✎ |
| SSIDs | `cvcue_list_ssids`, `cvcue_get_ssid`, `cvcue_ssid_usage`, `cvcue_delete_ssid`✎ |
| Events / WIPS | `cvcue_query_events`, `cvcue_event_summary`, `cvcue_list_rogue_aps`, `cvcue_rogue_ap_summary` |
| Troubleshooting | `cvcue_network_health`, `cvcue_client_events`, `cvcue_device_logs`, `cvcue_troubleshoot_client` |
| Wired | `cvcue_list_switches`, `cvcue_list_wired_clients` |
| Full API | `cvcue_api_modules` → `cvcue_api_search` → `cvcue_api_schema` → `cvcue_api_execute` |

✎ = mutating. These need writes enabled, and destructive ones also need `confirm=true`.
`cvcue_api_execute` refuses anything other than GET unless writes are enabled, and refuses write
bodies that contain the `***REDACTED***` placeholder (so a read-modify-write can't overwrite a
real secret with the mask).

## CV-CUE API notes

- **Paging:** `startindex` (a 0-based record offset) plus `pagesize`. Add
  `totalcountrequired=true` to get `totalCount`.
- **Scoping:** most endpoints take `locationid` and return data for that location's whole
  subtree. Location IDs come back as `{"type":"locallocationid","id":N}`; the tools flatten
  them to `N`.
- **Time:** `fromtime`/`totime` are epoch **milliseconds**. Some spec descriptions say
  microseconds, but the live server rejects µs values.
- **Versioning:** each module has its own version, chosen with the `Version` request header.
  When it's omitted the server uses its latest; `cvcue_api_execute` takes `version=` to pin one.
- **Locations:** `POST /locations` takes the *parent* folder with the new location under
  `children`; `cvcue_create_location` returns just the new location and its id.
- **Big responses:** `fields=[...]` does a selective fetch on many GETs (unsupported fields fail
  with `SELECTIVE_FETCH_OR_UPDATE_NOT_SUPPORTED_FOR_FIELD`). Device templates are ~200 KB each
  unless you pass `modelspecific=false`.

## Updating the bundled spec

The OpenAPI spec comes from Arista's public API portal at <https://apihelp.wifi.arista.com/api/wm>.
The portal publishes one file per module version; the script merges the newest version of every
module:

```bash
python scripts/fetch_spec.py          # rewrites src/cvcue_mcp/spec/cvcue_openapi.json
pip install .                         # reinstall so the server picks it up
```

## Development

```bash
pip install '.[http,dev]'
pytest                                # offline tests; the CV-CUE API is mocked
ruff check src tests
python scripts/gen_tool_docs.py       # regenerate the docs' tool reference
cd docs && npm install && npm run dev # docs site at localhost:4321/cv-cue-mcp/
```

On macOS, files under `~/Desktop` can get the `hidden` flag, which makes Python 3.12+ skip
editable-install `.pth` files. If `pip install -e .` leaves the package unimportable, use a
regular `pip install .` and reinstall after changes.

## License

MIT — see [LICENSE](LICENSE).
