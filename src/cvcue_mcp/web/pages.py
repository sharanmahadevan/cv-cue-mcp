"""Server-rendered HTML for the hosted sign-in app. Every dynamic value goes through esc()."""

from __future__ import annotations

import html
import time
from collections.abc import Iterable

from .store import Connection, User

PRODUCT = "CV-CUE MCP"
DOCS_URL = "https://sharanmahadevan.github.io/cv-cue-mcp/"
REPO_URL = "https://github.com/sharanmahadevan/cv-cue-mcp"


def esc(v: object) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = int(time.time() - ts)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit} ago"
    return "just now"


CSS = """
:root{--bg:#0a1220;--panel:#0f1a2b;--panel2:#13213a;--line:#1f2f48;--text:#e6edf6;--muted:#93a4bd;
--accent:#14b8a6;--accent2:#5eead4;--danger:#f87171;--ok:#34d399;--warn:#fbbf24;--radius:14px}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif}
a{color:var(--accent2);text-decoration:none}a:hover{text-decoration:underline}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
.brand{display:flex;align-items:center;gap:10px;font-weight:600}
.logo{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,#0f766e,#14b8a6);display:grid;place-items:center;color:#04201d;font-weight:800;font-size:13px}
.tag{font:600 11px ui-monospace,monospace;color:var(--accent2);background:#0b2f2c;border:1px solid #134e4a;padding:2px 7px;border-radius:6px}
/* landing */
.split{display:grid;grid-template-columns:1.05fr 1fr;min-height:100vh}
.hero{padding:44px 56px;display:flex;flex-direction:column;background:radial-gradient(1200px 600px at -10% -10%,#0f2a33 0%,transparent 60%),var(--bg);border-right:1px solid var(--line)}
.hero .main{margin:auto 0;max-width:520px}
.eyebrow{font:600 12px ui-monospace,monospace;letter-spacing:.08em;color:var(--accent2);text-transform:uppercase}
h1{font-size:52px;line-height:1.05;margin:14px 0 18px;letter-spacing:-.02em}
.lede{color:var(--muted);font-size:17px;margin:0 0 26px}
.checks{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.checks li{display:flex;gap:10px}.checks li:before{content:"✓";color:var(--accent);font-weight:700}
.foot{color:var(--muted);font-size:12.5px;margin-top:40px}.foot a{color:var(--muted);margin-right:12px}
.side{display:grid;place-items:center;padding:40px;background:#0c1626}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:28px}
.signin{width:100%;max-width:380px}
.signin h2{margin:0 0 6px;font-size:22px}.sub{color:var(--muted);font-size:14px;margin:0 0 18px}
.agree{display:flex;gap:10px;align-items:flex-start;font-size:14px;color:var(--muted);margin:0 0 16px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:9px 14px;border-radius:10px;font:inherit;font-weight:600;cursor:pointer}
.btn:hover{border-color:#2c4363;text-decoration:none}.btn.primary{background:var(--accent);border-color:var(--accent);color:#04201d}
.btn.primary:hover{background:#2dd4bf}.btn.danger{color:var(--danger)}.btn.small{padding:5px 10px;font-size:13px;border-radius:8px}
.btn[disabled],.btn.disabled{opacity:.45;pointer-events:none}.btn.block{width:100%;padding:12px}
.hint{color:var(--muted);font-size:13px;text-align:center;margin:14px 0 0}
/* app */
.top{display:flex;justify-content:space-between;align-items:center;padding:16px 28px;border-bottom:1px solid var(--line)}
.top .who{color:var(--muted);font-size:14px;display:flex;gap:14px;align-items:center}
.wrap{max-width:960px;margin:0 auto;padding:28px}
.wrap h2{font-size:18px;margin:0 0 4px}.wrap .card{margin-bottom:20px}
.urlbox{display:flex;gap:8px;margin:12px 0}.urlbox input{flex:1}
input[type=text],input[type=password],input[type=url]{width:100%;background:#0a1322;border:1px solid var(--line);color:var(--text);border-radius:9px;padding:9px 11px;font:inherit}
input:focus{outline:2px solid #134e4a;border-color:var(--accent)}
label.f{display:block;font-size:13px;color:var(--muted);margin:0 0 5px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.conn{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-top:12px;background:#0c1626}
.conn .name{font-weight:600}.meta{color:var(--muted);font-size:13px;display:flex;gap:14px;flex-wrap:wrap;margin:4px 0 10px}
.pill{font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.pill.def{color:var(--accent2);border-color:#134e4a;background:#0b2f2c}.pill.on{color:var(--warn);border-color:#4d3b0b}
.ok{color:var(--ok)}.bad{color:var(--danger)}
ol.steps{margin:8px 0 0;padding-left:20px;color:var(--muted)}ol.steps li{margin:3px 0}
.flash{padding:10px 14px;border-radius:10px;margin-bottom:18px;border:1px solid}
.flash.ok{background:#052e24;border-color:#065f46;color:#a7f3d0}.flash.err{background:#3a0d0d;border-color:#7f1d1d;color:#fecaca}
.consent{max-width:460px;margin:8vh auto;padding:0 20px}.consent ul{color:var(--muted);padding-left:20px}
.doc{max-width:760px;margin:0 auto;padding:36px 28px}.doc h1{font-size:34px}.doc h2{margin-top:28px}
.doc p,.doc li{color:#c9d5e6}
@media(max-width:880px){.split{grid-template-columns:1fr}.hero{padding:32px 24px;border-right:0}h1{font-size:38px}.grid2{grid-template-columns:1fr}}
"""

GOOGLE_G = (
    '<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3'
    'C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24'
    's8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1'
    ' 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2'
    'C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20'
    'H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>'
)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title><meta name=referrer content=same-origin><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def brand() -> str:
    return f'<div class=brand><div class=logo>CV</div>{PRODUCT} <span class=tag>for Arista CV-CUE</span></div>'


def footer_links() -> str:
    return (
        f'<a href="/terms">Terms</a><a href="/privacy">Privacy</a><a href="{DOCS_URL}">Docs</a>'
        f'<a href="{DOCS_URL}how-it-works/security/">Security</a><a href="{REPO_URL}">Source</a>'
    )


DISCLAIMER = (
    f"{PRODUCT} is an independent open-source project. It is not made, endorsed or supported by Arista Networks. "
    "Arista and CV-CUE are trademarks of Arista Networks, Inc.; Claude is a trademark of Anthropic."
)


def landing(next_url: str, google_enabled: bool, dev_login: bool, error: str | None = None) -> str:
    err = f'<div class="flash err">{esc(error)}</div>' if error else ""
    if google_enabled:
        action = (
            f'<form method=get action="/auth/google"><input type=hidden name=next value="{esc(next_url)}">'
            '<label class=agree><input type=checkbox name=agree value=1 required '
            "onchange=\"document.getElementById('g').disabled=!this.checked\"> "
            '<span>I agree to the <a href="/terms">Terms</a> and <a href="/privacy">Privacy notice</a>.</span></label>'
            f'<button id=g class="btn block" disabled>{GOOGLE_G} Continue with Google</button></form>'
        )
    else:
        action = '<p class=sub>Google sign-in is not configured on this server.</p>'
    if dev_login:
        action += (
            f'<form method=post action="/auth/dev" style="margin-top:14px"><input type=hidden name=next value="{esc(next_url)}">'
            '<input type=text name=email placeholder="dev@example.com" required> '
            '<button class="btn block" style="margin-top:8px">Dev sign-in (local only)</button></form>'
        )
    body = f"""
<div class=split>
 <section class=hero>{brand()}
  <div class=main>
   <div class=eyebrow>{PRODUCT} · for Arista Wi-Fi</div>
   <h1>Arista CV-CUE,<br>in Claude.</h1>
   <p class=lede>Ask about any location, access point, client or SSID. Troubleshoot a client's
   connection, review rogue APs, check network health, or reach any of the 613 CV-CUE API
   operations, in plain language.</p>
   <ul class=checks>
    <li>One connector URL for the whole CV-CUE API</li>
    <li>Several CV-CUE accounts; keys encrypted and never shown again</li>
    <li>Read-only unless you turn on writes for a connection</li>
   </ul>
  </div>
  <div class=foot>© {time.gmtime().tm_year} {PRODUCT} · {footer_links()}<p>{esc(DISCLAIMER)}</p></div>
 </section>
 <section class=side><div class="card signin">{err}
  <h2>Sign in</h2><p class=sub>With Google. Your CV-CUE connections and settings belong to this account.</p>
  {action}
  <p class=hint>Adding the connector in Claude? You'll come back here to approve it.</p>
  <p class=hint>Prefer not to store a key? <a href="{DOCS_URL}setup/connecting/#bring-your-own-key">Use your key directly</a>.</p>
 </div></section>
</div>"""
    return page(f"{PRODUCT} — Arista CV-CUE in Claude", body)


def topbar(user: User, csrf: str) -> str:
    return (
        f'<header class=top>{brand()}<div class=who><span>{esc(user.email)}</span>'
        f'<a href="{DOCS_URL}">Docs</a><form method=post action="/logout" style="margin:0">'
        f'<input type=hidden name=csrf value="{esc(csrf)}"><button class="btn small">Sign out</button></form></div></header>'
    )


def _conn_card(c: Connection, csrf: str, writes_allowed: bool) -> str:
    def post(action: str, label: str, cls: str = "btn small", extra: str = "", confirm: str = "") -> str:
        onsub = f' onsubmit="return confirm({esc(repr(confirm))})"' if confirm else ""
        return (f'<form method=post action="/connections/{esc(c.id)}/{action}" style="margin:0"{onsub}>'
                f'<input type=hidden name=csrf value="{esc(csrf)}">{extra}<button class="{cls}">{label}</button></form>')

    if c.last_tested_at is None:
        test = "not tested"
    else:
        cls = "ok" if c.last_test_ok else "bad"
        test = f'<span class={cls}>{"✓" if c.last_test_ok else "✗"} {esc(c.last_test_msg)}</span> · {ago(c.last_tested_at)}'
    pills = '<span class="pill def">default</span>' if c.is_default else ""
    pills += '<span class="pill on">writes on</span>' if c.allow_writes and writes_allowed else '<span class=pill>read-only</span>'
    writes_btn = post("writes", "Turn writes off" if c.allow_writes else "Turn writes on",
                      extra=f'<input type=hidden name=allow value={"0" if c.allow_writes else "1"}>') if writes_allowed else ""
    return f"""<div class=conn>
 <div class=row><span class=name>{esc(c.name)}</span>{pills}</div>
 <div class=meta><span>Key <code>{esc(c.key_id_masked)}</code></span>
  <span>Server <code>{esc(c.base_url) or "auto (Launchpad)"}</code></span>{f"<span>CID <code>{esc(c.cid)}</code></span>" if c.cid else ""}
  <span>Test: {test}</span></div>
 <div class=row>{post("test", "Test connection")}{"" if c.is_default else post("default", "Make default")}{writes_btn}
  {post("delete", "Delete", "btn small danger", confirm=f"Delete connection {c.name}? Claude will stop using it.")}</div>
</div>"""


def dashboard(user: User, conns: Iterable[Connection], grants: list[dict], csrf: str, mcp_url: str,
              writes_allowed: bool, flash: tuple[str, str] | None = None) -> str:
    conns = list(conns)
    fl = f'<div class="flash {esc(flash[0])}">{esc(flash[1])}</div>' if flash else ""
    conn_html = "".join(_conn_card(c, csrf, writes_allowed) for c in conns) or (
        '<p class=sub style="margin-top:12px">No connections yet. Add your CV-CUE API key below.</p>')
    grants_html = "".join(
        f'<div class=conn><div class=row><span class=name>{esc(g["client_name"])}</span>'
        f'<span class=pill>since {ago(g["since"])}</span></div><div class=row style="margin-top:8px">'
        f'<form method=post action="/grants/revoke" style="margin:0"><input type=hidden name=csrf value="{esc(csrf)}">'
        f'<input type=hidden name=client_id value="{esc(g["client_id"])}"><button class="btn small danger">Disconnect</button>'
        '</form></div></div>' for g in grants
    ) or '<p class=sub style="margin-top:12px">No apps connected yet.</p>'
    writes_note = "" if writes_allowed else (
        '<p class=sub>Writes are disabled on this server, so every connection is read-only.</p>')
    body = f"""{topbar(user, csrf)}<main class=wrap>{fl}
<section class=card><h2>Your connector URL</h2>
 <p class=sub>Add this URL to Claude as a custom connector. Claude will send you back here to approve it.</p>
 <div class=urlbox><input type=text readonly value="{esc(mcp_url)}" id=u>
 <button class="btn primary" onclick="navigator.clipboard.writeText(document.getElementById('u').value);this.textContent='Copied'">Copy</button></div>
 <ol class=steps><li>In Claude, open <b>Settings → Connectors → Add custom connector</b>.</li>
 <li>Name it <b>CV-CUE</b>, paste the URL and choose <b>Add</b>, then <b>Connect</b>.</li>
 <li>Approve the request on the page that opens. Claude then uses your <b>default</b> connection.</li></ol>
 <p class=sub style="margin-top:10px">Claude Code: <code>claude mcp add --transport http cv-cue {esc(mcp_url)}</code>, then <code>/mcp</code> to sign in.</p>
</section>
<section class=card><h2>CV-CUE connections</h2>
 <p class=sub>Each connection is one CV-CUE API key. Claude uses the default one; ask it to switch, or change the default here.</p>
 {writes_note}{conn_html}
</section>
<section class=card><h2>Add a connection</h2>
 <p class=sub>Create a key in <b>Launchpad → Admin → Keys</b>. Its role limits what Claude can do. The key value is
 encrypted and can't be viewed again.</p>
 <form method=post action="/connections"><input type=hidden name=csrf value="{esc(csrf)}">
 <div class=grid2><div><label class=f>Name</label><input type=text name=name placeholder="HQ production" required maxlength=60></div>
 <div><label class=f>Customer ID (optional)</label><input type=text name=cid placeholder="Only for multi-customer keys" maxlength=40></div>
 <div><label class=f>Key ID</label><input type=text name=key_id placeholder="KEY-ATN…" required autocomplete=off maxlength=200></div>
 <div><label class=f>Key value</label><input type=password name=key_value required autocomplete=new-password maxlength=500></div></div>
 <div style="margin-top:14px"><label class=f>API base URL (optional, found automatically)</label>
 <input type=url name=base_url placeholder="https://awmXXXXX-c4.srv.wifi.arista.com/wifi/api" maxlength=300></div>
 {"<label class=agree style='margin-top:14px'><input type=checkbox name=allow_writes value=1> <span>Allow writes (reboot, disconnect, delete, PUT/POST) for this connection</span></label>" if writes_allowed else ""}
 <div class=row style="margin-top:14px"><button class="btn primary">Save and test</button></div></form>
</section>
<section class=card><h2>Connected apps</h2><p class=sub>Apps you've approved. Disconnecting signs them out immediately.</p>{grants_html}</section>
<section class=card><h2>Delete account</h2><p class=sub>Removes your connections, encrypted keys and every app approval. This can't be undone.</p>
 <form method=post action="/account/delete" onsubmit="return confirm('Delete your account and all stored keys?')">
 <input type=hidden name=csrf value="{esc(csrf)}"><button class="btn danger">Delete my account</button></form></section>
<p class=sub style="text-align:center">{footer_links()}</p>
</main>"""
    return page(f"{PRODUCT} — Dashboard", body)


def consent(user: User, client_name: str, redirect_host: str, rid: str, csrf: str, default: Connection | None,
            n_conns: int) -> str:
    if default is None:
        inner = (f'<p>You need a CV-CUE connection before {esc(client_name)} can use this server.</p>'
                 f'<a class="btn primary block" href="/dashboard?return={esc(rid)}">Add a connection</a>')
    else:
        inner = f"""<p class=sub>Signed in as {esc(user.email)}</p>
<p><b>{esc(client_name)}</b> wants to use {PRODUCT} on your behalf.</p>
<ul><li>It will use your default connection <b>{esc(default.name)}</b>{f" (one of {n_conns})" if n_conns > 1 else ""}.</li>
<li>It can do anything that connection's API key can do{", including writes" if default.allow_writes else ", read-only"}.</li>
<li>It never sees your key. You can disconnect it at any time from the dashboard.</li></ul>
<p class=sub>You'll return to <code>{esc(redirect_host)}</code>.</p>
<form method=post action="/consent"><input type=hidden name=csrf value="{esc(csrf)}"><input type=hidden name=request value="{esc(rid)}">
<div class=row><button name=decision value=allow class="btn primary">Allow</button>
<button name=decision value=deny class=btn>Deny</button></div></form>"""
    return page(f"Approve {client_name}", f'<div class=consent><div style="margin-bottom:18px">{brand()}</div>'
                f'<div class=card><h2 style="margin-top:0">Approve access</h2>{inner}</div></div>')


def message(title: str, text: str, link: str = "/", link_label: str = "Back") -> str:
    return page(title, f'<div class=consent><div style="margin-bottom:18px">{brand()}</div><div class=card>'
                f'<h2 style="margin-top:0">{esc(title)}</h2><p>{esc(text)}</p><a class=btn href="{esc(link)}">{esc(link_label)}</a></div></div>')


TERMS = f"""<h1>Terms of Service</h1>
<p class=sub>Plain-language terms for the hosted {PRODUCT} service. The software itself is MIT-licensed open source.</p>
<h2>The service</h2><p>{PRODUCT} connects MCP clients such as Claude to your Arista CV-CUE account using API keys you provide.
It is provided as is, without warranty of any kind, and may change or stop at any time.</p>
<h2>Your responsibilities</h2><ul><li>Only add API keys you are authorised to use, and give them the narrowest role that works.</li>
<li>You are responsible for actions an AI assistant takes with your connections, including any writes you enable.</li>
<li>Don't use the service to attack, overload or probe systems you don't own.</li></ul>
<h2>Liability</h2><p>To the extent the law allows, the operators are not liable for any loss arising from use of the service,
including changes made to your network through it.</p>
<h2>Not affiliated</h2><p>{esc(DISCLAIMER)}</p>"""

PRIVACY = """<h1>Privacy notice</h1>
<h2>What we store</h2><ul><li>Your Google account id, email and name, to identify your account.</li>
<li>Your CV-CUE connections: name, key ID, optional base URL and customer ID, and the key value encrypted with AES-256-GCM.</li>
<li>OAuth records for apps you approve, with tokens stored only as SHA-256 hashes.</li></ul>
<h2>What we don't store</h2><p>The contents of your CV-CUE network data. Tool results pass through the server to your MCP client
and are not saved. Secrets returned by CV-CUE (Wi-Fi passphrases, RADIUS secrets) are masked before they reach the AI.</p>
<h2>Who sees it</h2><p>Your key value is decrypted only in server memory to open a CV-CUE session, and is never sent to Claude
or any AI model. Google receives the sign-in request. The service runs on Fly.io.</p>
<h2>Deleting your data</h2><p>Delete a connection or your whole account from the dashboard at any time. Deletion is immediate.</p>"""


def legal(kind: str) -> str:
    body = TERMS if kind == "terms" else PRIVACY
    return page(f"{PRODUCT} — {kind.title()}", f'<header class=top>{brand()}<a class="btn small" href="/">Home</a></header>'
                f'<main class=doc>{body}<p class=sub style="margin-top:30px">{footer_links()}</p></main>')
