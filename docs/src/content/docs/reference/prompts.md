---
title: Workflow prompts
description: Ready-made workflows in Claude's + menu — RF review, client deep-dive, can't-connect diagnosis, as-built document, rogue AP review and configuration audit.
---

CV-CUE MCP ships six **workflow prompts**. They appear in Claude's **+** menu under the
connector (in Claude Code, as `/mcp__cv-cue__<name>` commands). Picking one fills in a tested
step-by-step request that tells Claude which tools to use and what to report. Nothing runs until
you send the message, and you can edit it first.

All six are **read-only**: they tell Claude not to reboot, disconnect, delete or change anything,
and to recommend fixes instead.

| Prompt | Arguments | What you get |
|---|---|---|
| **RF health review** | `location` (optional), `hours` (default 24) | Channel plan per band, APs sharing channels, 2.4 GHz off 1/6/11, client load per AP, SSIDs per radio, RF events, and prioritised fixes |
| **Client deep-dive** | `mac`, `hours` (default 24) | Where the client is now, a timeline of associations and roams, failures with evidence, the most likely cause and next steps |
| **Why can't this client connect?** | `mac`, `ssid` (optional) | The stage where joining fails (association, authentication, DHCP), the evidence, the cause and the fix |
| **Site as-built document** | `location` | A document with the location tree, AP inventory, RF plan by floor, SSIDs, wired side and current health |
| **Rogue AP and WIPS review** | `location` (optional) | Risk summary, rogue and uncategorised APs that need action (wired, evil-twin, strong signal), and WIPS policy suggestions |
| **Configuration audit** | `location` (optional) | SSID security, firmware drift, APs without a floor, disabled radios, unused templates, each with a severity and fix |

`location` takes a location name or ID; without one, the prompt covers the whole account. If a
name matches more than one location, Claude asks which you mean.

## Tips

- Prompts work best with a connection whose key can read the whole scope. A key limited to some
  locations will give a partial report; Claude says what it couldn't see.
- Ask for a follow-up in the same chat, for example "turn the fixes into a change plan", to build
  on the report.
- Want Claude to make a recommended change? Ask in plain words. It still goes through
  [the write layers](/cv-cue-mcp/guides/writes/), including confirm before write.
