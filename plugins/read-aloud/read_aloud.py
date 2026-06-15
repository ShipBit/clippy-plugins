#!/usr/bin/env python3
"""Beispiel-Plugin: Hotkey-Trigger + TTS.

Auf den im Manifest deklarierten Hotkey (`contributes.hotkey`) schickt der Host
ein ``trigger``-Event (Quelle ``hotkey``). Das Plugin liest dann den Text aus der
Zwischenablage (``clipboard.readText``) und lässt ihn lokal vorlesen
(``tts.speak``). Zeigt zugleich das Request/Response-Muster der Host-API
(``call``) neben Fire-and-forget (``notify``).
"""
import json
import sys

_next_id = 0


def _readline():
    line = sys.stdin.readline()
    if not line:  # Host hat stdin geschlossen → sauber beenden
        raise SystemExit(0)
    return line.strip()


def call(method, params=None):
    """Request senden und auf die Antwort mit passender id warten."""
    global _next_id
    _next_id += 1
    req = {"jsonrpc": "2.0", "id": _next_id, "method": method}
    if params is not None:
        req["params"] = params
    sys.stdout.write(json.dumps(req) + "\n")
    sys.stdout.flush()
    while True:
        try:
            msg = json.loads(_readline())
        except json.JSONDecodeError:
            continue
        if msg.get("id") == _next_id:
            return msg.get("result")


def notify(method, params):
    """Fire-and-forget (ohne id) — keine Antwort erwartet."""
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
    sys.stdout.flush()


def main():
    while True:
        try:
            msg = json.loads(_readline())
        except json.JSONDecodeError:
            continue
        params = msg.get("params") or {}
        if msg.get("method") == "event" and params.get("topic") == "trigger":
            result = call("clipboard.readText") or {}
            text = (result.get("text") or "").strip()
            if text:
                notify("tts.speak", {"text": text})


if __name__ == "__main__":
    main()
