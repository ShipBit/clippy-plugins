#!/usr/bin/env python3
"""Visuelles Tagebuch: Interval-Trigger + Vision + LLM -> Markdown-Journal.

Auf den Interval-Trigger (Manifest: contributes.interval) macht der Host einen
Screenshot des Monitors unter der Maus (``vision.capture``). Das Plugin schickt
das Bild zusammen mit einem konfigurierbaren Prompt an das lokale multimodale
Modell (``llm.chat``, Bild im OpenAI-Vision-Format) und haengt die Antwort mit
Zeitstempel an eine Markdown-Datei an (eine Datei pro Tag). Alles bleibt lokal.

Zeigt zugleich, dass ein Sidecar-Plugin eigene Dateien schreiben darf (eigener
Prozess) und wie String-Einstellungen ueber ``storage.string`` gelesen werden.
"""
import json
import os
import sys
from datetime import datetime

# stdio ist laut Protokoll UTF-8. Auf Windows ist Pythons Default sonst die
# Locale-Codepage → Umlaute in den Host-Nachrichten kämen falsch an. Der Host
# setzt dafür zwar PYTHONUTF8, aber hier doppelt absichern (schadet nie).
for _stream in (sys.stdin, sys.stdout):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_next_id = 0

# Muss zum Manifest-Default passen (greift, wenn der Nutzer nichts gesetzt hat).
DEFAULT_PROMPT = (
    "Schau dir diesen Screenshot an und beschreibe in 1–2 Sätzen in der Ich-Form, "
    "woran ich gerade arbeite — sachlich, als Tagebuch-Eintrag. Wenn nichts "
    "Aussagekräftiges zu sehen ist, antworte nur mit: SKIP"
)


def _readline():
    line = sys.stdin.readline()
    if not line:  # Host hat stdin geschlossen -> sauber beenden
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
            if "error" in msg:  # Host hat den Aufruf abgelehnt -> sichtbar machen
                print("RPC-Fehler bei {}: {}".format(method, msg["error"]), file=sys.stderr)
            return msg.get("result")


def notify(method, params):
    """Fire-and-forget (ohne id)."""
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
    sys.stdout.flush()


def journal_path():
    folder = (call("storage.string", {"key": "folder", "default": ""}) or "").strip()
    if not folder:
        home = os.path.expanduser("~")
        docs = os.path.join(home, "Documents")
        folder = docs if os.path.isdir(docs) else home
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "clippy-journal-{:%Y-%m-%d}.md".format(datetime.now()))


def make_entry():
    shot = call("vision.capture") or {}
    image = shot.get("image")
    if not image:
        print("vision.capture lieferte kein Bild", file=sys.stderr)
        return

    prompt = call("storage.string", {"key": "prompt", "default": DEFAULT_PROMPT}) or DEFAULT_PROMPT
    res = call("llm.chat", {"messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image}},
    ]}]})
    if not res or not res.get("content"):
        print("llm.chat ohne Antwort - Modell geladen und multimodal?", file=sys.stderr)
        return

    text = res["content"].strip()
    if not text or text.upper().startswith("SKIP"):
        print("KI meldet 'SKIP' (nichts Aussagekraeftiges) - kein Eintrag", file=sys.stderr)
        return  # nichts Aussagekraeftiges -> keinen Eintrag schreiben

    path = journal_path()
    new_file = not os.path.exists(path)
    now = datetime.now()
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("# Tagebuch {:%Y-%m-%d}\n\n".format(now))
        f.write("## {:%H:%M}\n\n{}\n\n".format(now, text))

    want_bubble = call("storage.bool", {"key": "notify", "default": False})
    print("Eintrag geschrieben: {} (notify={})".format(path, want_bubble), file=sys.stderr)
    if want_bubble:
        notify("ui.showBubble", {"kind": "journal", "text": "Tagebuch-Eintrag gespeichert"})


def main():
    while True:
        try:
            msg = json.loads(_readline())
        except json.JSONDecodeError:
            continue
        params = msg.get("params") or {}
        if msg.get("method") == "event" and params.get("topic") == "trigger":
            try:
                make_entry()
            except SystemExit:
                raise
            except Exception as e:  # ein einzelner Fehlversuch darf das Plugin nicht beenden
                print("Journal-Fehler: {}".format(e), file=sys.stderr)


if __name__ == "__main__":
    main()
