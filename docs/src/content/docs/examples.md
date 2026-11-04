---
title: Examples
description: Worked examples of asking Claude to do real CV-CUE work, and the tools it uses.
---

These show what Claude does behind the scenes, so you know what to expect and how to phrase
requests.

## Fleet health check

> "Give me a health summary of all my APs. Anything offline or misbehaving?"

Claude calls `cvcue_ap_health_summary`, which pages through every managed AP and returns counts
by model, firmware, upgrade and config-push status, plus the offline APs and those with problems
(crashes, low power, tunnels down, config errors). For details on a specific AP it follows up
with `cvcue_get_ap`.

## Why can't this client connect?

> "The laptop with MAC 3c:22:fb:… keeps dropping off Wi-Fi this morning. Why?"

Claude runs `cvcue_troubleshoot_client`, which returns the client's current record, recent
associations, connection logs, failure events and CV-CUE's own root-cause inferences, then
explains the pattern: for example repeated DHCP timeouts on one AP, or authentication failures
after a password change.

## Compare sites

> "How did network health compare across my sites over the last 24 hours?"

`cvcue_network_health` returns connectivity, performance, application and infrastructure
scores for a location and each child location. Claude ranks the sites and points out the weak
spot in each, such as high retry rates or low coverage.

## Rogue AP review

> "Are there rogue APs with clients on them? Which vendors and SSIDs?"

`cvcue_rogue_ap_summary` gives the counts by classification, rogues with associated clients, and
top vendors and SSIDs. `cvcue_list_rogue_aps` lists them with signal and location.

## Something the curated tools don't cover

> "Which device templates exist, and which locations use them?"

Claude uses discovery:

1. `cvcue_api_search` with `keyword: "device template"` finds `GET /deviceconfiguration/devicetemplates`.
2. `cvcue_api_schema` shows its parameters, including `fields` and `modelspecific`.
3. `cvcue_api_execute` with `fields=["templateId","templateName"]` and `modelspecific=false`
   keeps the response small.
4. For each template, `GET /deviceconfiguration/devicetemplates/{templateid}/references`.

## Switching accounts

> "Switch to my Lab connection and list the SSIDs there."

Claude calls `cvcue_use_connection` with `name: "Lab"`, then `cvcue_list_ssids`. The switch
sticks until you change it again.

## Making a change

> "Create a folder called 'Building C' under the root location."

If writes are on for the connection, Claude calls `cvcue_create_location` and reports the new
location's ID. If they're off, the tool refuses and Claude tells you how to enable writes. For
reboots, disconnects and deletes, Claude asks you to confirm first.
