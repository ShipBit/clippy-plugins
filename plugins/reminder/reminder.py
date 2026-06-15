#!/usr/bin/env python3
"""Beispiel-Plugin: Interval-Trigger.

Der Host schickt periodisch ein ``trigger``-Event (Quelle ``interval``, siehe
``contributes.interval`` im Manifest, per Setting ``pluginInterval.<id>``
änderbar). Das Plugin zeigt dann eine Blase — keine KI, kein Netz, nur die
Host-API ``ui.showBubble``. Ein nicht-Standard ``kind`` lässt Clippy den Text
als Titel zeigen (nur Schließen).

Derselbe ``trigger``-Mechanismus kommt auch per Hotkey (Quelle ``hotkey``).
"""
import json
import sys


def send(method, params):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    params = msg.get("params") or {}
    if msg.get("method") == "event" and params.get("topic") == "trigger":
        send("ui.showBubble", {"kind": "reminder", "text": "💧 Zeit für einen Schluck Wasser!"})
