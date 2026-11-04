# cv-cue-mcp — MCP server for Arista CV-CUE

An [MCP](https://modelcontextprotocol.io) server for **Arista CV-CUE** (CloudVision Cognitive
Unified Edge), Arista's cloud-managed Wi-Fi platform.

- **30 curated tools** for day-to-day work: APs, clients, SSIDs, locations, events, WIPS/rogues,
  troubleshooting, switches
- **4 discovery tools** that open up the **whole CV-CUE REST API** (613 operations across 24
  modules) without registering hundreds of tools
- Every tool returns the same `{ok, data, message}` envelope
- Secrets (PSK passphrases, RADIUS secrets, …) are **redacted** before they reach the model

It runs in two ways:

| Mode | Who it's for | Credentials |
|---|---|---|
| **Local** (stdio, or `--http`) | You, on your own machine | Your key in `.env` / env vars |
| **Hosted** (`--hosted`) | A shared public endpoint, e.g. on Fly.io | **None stored** — each caller sends their own key |

> Not affiliated with or endorsed by Arista Networks. "Arista" and "CV-CUE" are trademarks of
> Arista Networks, Inc.

---

## Using a hosted server (bring your own key)

Get an API key from **Launchpad → Admin → Keys**, then point your MCP client at the server's
`/mcp` endpoint with your key in the `Authorization` header:

```
Authorization: Bearer <key_id>:<key_value>
```

| Header | Required | Purpose |
|---|---|---|
| `Authorization: Bearer <key_id>:<key_value>` | yes* | Your CV-CUE API key |
| `X-CVCUE-Key-Id` + `X-CVCUE-Key-Value` | yes* | Alternative to the bearer header |
| `X-CVCUE-Base-URL` | no | Your API base URL. Discovered through Launchpad when omitted. Must be `https://…wifi.arista.com`. |
| `X-CVCUE-CID` | no | Customer ID, for keys that reach several customers |
| `X-CVCUE-Enable-Writes: true` | no | Opt in to mutating calls (only works if the operator allows writes) |

\* one of the two forms.

**Claude Code**

```bash
claude mcp add --transport http arista-cv-cue https://<your-app>.fly.dev/mcp \
  --header "Authorization: Bearer $CVCUE_KEY_ID:$CVCUE_KEY_VALUE"
```

**Claude Desktop / other stdio-only clients** — bridge with
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "arista-cv-cue": {
      "command": "npx",
      "args": ["mcp-remote", "https://<your-app>.fly.dev/mcp",
               "--header", "Authorization:${CVCUE_AUTH}"],
      "env": { "CVCUE_AUTH": "Bearer <key_id>:<key_value>" }
    }
  }
}
```

Any client that lets you set HTTP headers on a streamable-HTTP MCP server works the same way.
Connector UIs that only support OAuth can't pass a key yet.

### What the hosted server does with your key

- It never writes your key to disk or logs. Requests carry it; the server keeps a logged-in
  CV-CUE session in memory, keyed by a SHA-256 hash of your credentials, and logs it out after
  15 minutes idle (or on restart).
- Each caller gets their own CV-CUE session — callers never share a client.
- `X-CVCUE-Base-URL` is restricted to `*.wifi.arista.com` over HTTPS (no SSRF to other hosts).
- Writes need **both** the operator's `CVCUE_ENABLE_WRITES=true` and your
  `X-CVCUE-Enable-Writes: true`. Destructive tools additionally need `confirm=true`.
- Your key is still sent to a server someone else operates. Prefer a key with the narrowest role
  that does what you need, or run your own copy (below).

---

## Deploying your own hosted server on Fly.io

```bash
git clone https://github.com/sharanmahadevan/cv-cue-mcp && cd cv-cue-mcp
fly launch --no-deploy --copy-config     # pick an app name; keeps fly.toml
fly deploy
curl https://<your-app>.fly.dev/healthz  # {"status":"ok","sessions":0}
```

No secrets are needed — the server stores no credentials. Operator settings live in
`fly.toml` under `[env]`:

| Variable | Default | Purpose |
|---|---|---|
| `CVCUE_ENABLE_WRITES` | `false` | Ceiling for mutating calls; callers must still opt in per request |
| `CVCUE_ALLOWED_HOST_SUFFIXES` | `.wifi.arista.com` | Hosts callers may target with `X-CVCUE-Base-URL` |
| `CVCUE_REDACT_SECRETS` | `true` | Mask passphrases/secrets in tool output |
| `CVCUE_MAX_RESPONSE_CHARS` | `100000` | `cvcue_api_execute` refuses larger responses and returns a shape preview |
| `CVCUE_POOL_MAX` / `CVCUE_POOL_IDLE_TTL` | `256` / `900` | Cached sessions and idle seconds |
| `CVCUE_SOURCE_URL` | — | Link shown at `GET /` |

Endpoints: `POST /mcp` (MCP, stateless streamable HTTP with JSON responses), `GET /healthz`,
`GET /` (connection info).

Run the same image anywhere else:

```bash
docker build -t cv-cue-mcp . && docker run -p 8080:8080 cv-cue-mcp
```

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

| Area | Tools |
|---|---|
| Session / system | `cvcue_session_info`, `cvcue_server_info` |
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
```

On macOS, files under `~/Desktop` can get the `hidden` flag, which makes Python 3.12+ skip
editable-install `.pth` files. If `pip install -e .` leaves the package unimportable, use a
regular `pip install .` and reinstall after changes.

## License

MIT — see [LICENSE](LICENSE).
