"""
Workflow prompts: ready-made starting points that MCP clients show in their
prompt menu (the "+" menu in Claude). Choosing one only drafts the first
message; nothing runs until the user sends it. All of them are read-only.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

READ_ONLY = ("This is a read-only review: do not reboot, disconnect, delete or change anything, "
             "even if a fix looks obvious. Recommend changes instead.")


def _scope(location: str) -> str:
    loc = location.strip()
    if not loc:
        return ("Scope: the whole account. Start with cvcue_list_locations and say which top-level "
                "locations you covered.")
    return (f"Scope: the location \"{loc}\" and everything under it. Find its id with "
            "cvcue_list_locations (match by name, or treat a number as the id) and pass it as "
            "location_id wherever a tool accepts one. If several locations match, ask which one.")


def _hours(hours: str, default: int = 24) -> int:
    try:
        return max(1, min(int(float(hours)), 24 * 30))
    except (TypeError, ValueError):
        return default


PROMPTS: list[tuple[str, str, str]] = [
    ("cvcue_rf_health_review", "RF health review",
     "Check channels, radio load and AP health for a location, then list prioritised fixes."),
    ("cvcue_client_deep_dive", "Client deep-dive",
     "Everything about one client MAC: where it connected, roams, events, health and a verdict."),
    ("cvcue_client_cant_connect", "Why can't this client connect?",
     "Work out why a client fails to join Wi-Fi, from its events, associations and the SSID's settings."),
    ("cvcue_site_as_built", "Site as-built document",
     "Write an as-built document for a site: locations, APs, SSIDs, switches and current health."),
    ("cvcue_rogue_review", "Rogue AP and WIPS review",
     "Review rogue, external and uncategorised APs and say which ones need action."),
    ("cvcue_config_audit", "Configuration audit",
     "Audit SSID profiles, AP state and firmware for risky or inconsistent settings."),
]


def register(mcp: FastMCP) -> None:
    (rf, deep, cant, asbuilt, rogue, audit) = PROMPTS

    @mcp.prompt(name=rf[0], title=rf[1], description=rf[2])
    def rf_health_review(location: str = "", hours: str = "24") -> str:
        h = _hours(hours)
        return f"""Run an RF health review in Arista CV-CUE.
{_scope(location)}
Time window: the last {h} hours.

1. cvcue_network_health and cvcue_ap_health_summary for the scope: APs up/down, clients, top problems.
2. cvcue_list_radios: per band, the channel and width of every radio. Flag APs sharing a channel
   in the same location, 2.4 GHz radios off channels 1/6/11, and 40 MHz or wider on 2.4 GHz.
3. Client load per AP and per radio (cvcue_list_clients, cvcue_client_health_summary). Name the
   busiest APs and any with many clients on 2.4 GHz.
4. cvcue_ssid_usage: count SSIDs broadcast per radio; more than 4 on a radio wastes airtime.
5. cvcue_event_summary for RF events (interference, channel changes, radar/DFS) in the window.

Finish with a short report: a one-line verdict, a table of the problem APs (name, band, channel,
clients, issue), and a numbered list of fixes, most impactful first. {READ_ONLY}"""

    @mcp.prompt(name=deep[0], title=deep[1], description=deep[2])
    def client_deep_dive(mac: str, hours: str = "24") -> str:
        h = _hours(hours)
        return f"""Do a deep-dive on the Wi-Fi client {mac.strip()} in Arista CV-CUE, covering the last {h} hours.

1. cvcue_find_client: is it connected now, on which AP, SSID, band, channel, RSSI/SNR, data rate,
   IP, OS and username.
2. cvcue_client_association_history: every association in the window. Build a timeline of
   APs and SSIDs, and note sticky-client or ping-pong roaming.
3. cvcue_client_events and cvcue_troubleshoot_client: authentication, DHCP and association failures.
4. Check the AP it uses most (cvcue_get_ap): status, uptime, clients and channel.

Report: a summary (who, where, healthy or not), the timeline, problems found with evidence, the
most likely cause, and next steps. {READ_ONLY}"""

    @mcp.prompt(name=cant[0], title=cant[1], description=cant[2])
    def client_cant_connect(mac: str, ssid: str = "") -> str:
        target = f' to the SSID "{ssid.strip()}"' if ssid.strip() else ""
        return f"""The Wi-Fi client {mac.strip()} can't connect{target}. Work out why, using Arista CV-CUE.

1. cvcue_troubleshoot_client and cvcue_client_events for the last 24 hours. Find where the
   connection stops: association, 802.1X/PSK authentication, DHCP, or after getting an address.
2. cvcue_client_association_history: did it ever connect, and where?
3. If an SSID is involved, cvcue_get_ssid: security mode, band, VLAN, RADIUS servers and any
   client limits or access rules that could reject it. (Passphrases are masked; don't ask for them.)
4. Check the APs it tried (cvcue_get_ap) for being down, overloaded or not broadcasting that SSID.

Answer with: the stage where it fails, the evidence (event names and times), the most likely
cause, and the fix, plus what to check on the device itself if the network side looks fine.
{READ_ONLY}"""

    @mcp.prompt(name=asbuilt[0], title=asbuilt[1], description=asbuilt[2])
    def site_as_built(location: str) -> str:
        return f"""Write an as-built document for a site from Arista CV-CUE.
{_scope(location)}

Gather: the location tree (folders and floors); every AP with name, model, MAC, IP, firmware,
floor and status (cvcue_list_aps); radios with band, channel and width (cvcue_list_radios); SSID
profiles with security, band and VLAN (cvcue_list_ssids, cvcue_get_ssid; secrets stay masked);
switches and wired clients if any (cvcue_list_switches); and current health
(cvcue_network_health).

Write it as a clean document with these sections: Overview (counts, generated date), Location
hierarchy, Access points (table), RF plan (table by floor), SSIDs (table), Wired, Current health
and open issues, Appendix (anything that didn't fit). Note any data you couldn't get. {READ_ONLY}"""

    @mcp.prompt(name=rogue[0], title=rogue[1], description=rogue[2])
    def rogue_review(location: str = "") -> str:
        return f"""Review rogue and neighbouring APs (WIPS) in Arista CV-CUE.
{_scope(location)}

1. cvcue_rogue_ap_summary: counts by classification (rogue, external, uncategorised, authorised).
2. cvcue_list_rogue_aps for rogue and uncategorised APs: SSID, BSSID, vendor, signal, which of our
   APs hear it, first and last seen, whether it is on our wired network.
3. Pay most attention to APs on our wired network, APs broadcasting one of our SSID names
   (possible evil twin), and strong signals inside our buildings.

Report: a risk summary, a table of APs needing action (with why), APs that look safe to mark
external, and recommended WIPS policy changes. {READ_ONLY}"""

    @mcp.prompt(name=audit[0], title=audit[1], description=audit[2])
    def config_audit(location: str = "") -> str:
        return f"""Audit the configuration and state of Arista CV-CUE.
{_scope(location)}

Check and report on:
- SSID profiles (cvcue_list_ssids, cvcue_get_ssid): open or WPA2-PSK-only networks where
  WPA3 or 802.1X would fit, WPA3 transition mode, missing PMF, hidden SSIDs, inconsistent VLANs,
  SSIDs that exist but aren't used (cvcue_ssid_usage).
- APs (cvcue_list_aps): mixed firmware versions, APs down or never seen, APs without a floor,
  duplicate names.
- Radios (cvcue_list_radios): radios turned off, unusual transmit power or channel widths.
- Device templates via the API (/deviceconfiguration/devicetemplates with modelspecific=false):
  how many, which are unused.

Give each finding a severity (high, medium, low), the evidence, and the fix. End with the top
five changes to make first. {READ_ONLY}"""
