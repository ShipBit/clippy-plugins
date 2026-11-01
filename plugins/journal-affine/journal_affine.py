#!/usr/bin/env python3
"""Tagebuch in AFFiNE: Interval-Trigger + Vision + LLM -> AFFiNE-Journal.

Wie journal-cam: Auf den Interval-Trigger macht der Host einen Screenshot
(``vision.capture``), die lokale KI beschreibt ihn (``llm.chat``). Anders als
dort wird nicht jede Beschreibung ein Eintrag: Die Beobachtungen sammeln sich
lokal (``observations.jsonl``), und erst nach einem Block (Einstellung
``block``, Standard 30 Minuten) macht die KI daraus einen kurzen Eintrag
``## HH:MM–HH:MM``. Das hält das Tagebuch knapp, und das Modell sieht mehrere
Beobachtungen im Zusammenhang statt eines einzelnen Screenshots.

Die Einträge gehen nach AFFiNE: ein Doc pro Tag, als nativer Journal-Eintrag
markiert und im Ordner der Einstellung ``folder`` abgelegt.

AFFiNE spricht das Plugin über den Community-MCP-Server ``affine-mcp-server``
(stdio, per ``npx`` in fester Version, braucht Node.js). Die eingebauten
MCP-Schreibtools von AFFiNE sind in Stable-Builds gesperrt. Login und Workspace
kommen aus der Config von affine-mcp (einmalig
``npx -y -p affine-mcp-server@3.10.2 affine-mcp login --save-credentials``),
das Plugin selbst kennt keine Zugangsdaten.

Optional (Einstellung ``t3``) kommen gesettlete Threads aus T3 Code dazu, siehe
``t3_threads.py``.

Einträge landen zuerst in einer Warteschlange (``queue.jsonl``) und werden
erst nach erfolgreichem Schreiben entfernt. Ist AFFiNE nicht erreichbar,
liefert der nächste Trigger alles nach.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime

import t3_threads

for _stream in (sys.stdin, sys.stdout):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = t3_threads.state_dir("clippy-journal-affine")
QUEUE_FILE = os.path.join(STATE_DIR, "queue.jsonl")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
OBS_FILE = os.path.join(STATE_DIR, "observations.jsonl")
MCP_VERSION = "3.10.2"  # affine-mcp-server, bewusst gepinnt
MCP_LOG = os.path.join(STATE_DIR, "affine-mcp.log")
MCP_TIMEOUT = 120  # pro Sitzung; hängt affine-mcp, wird es beendet

# Müssen zu den Manifest-Defaults passen.
DEFAULT_PROMPT = (
    "Notiere im Telegrammstil (höchstens 25 Wörter), was auf diesem Screenshot zu "
    "sehen ist: App, Projekt bzw. Repo, Datei oder Webseite und Thema bzw. Tätigkeit."
    " Übernimm konkrete Namen, die sichtbar sind (Fenster- und Thread-Titel, "
    "Dateinamen, Überschriften). Nur was sichtbar ist, nicht raten. Wenn nichts "
    "Aussagekräftiges zu sehen ist (Sperrbildschirm, leerer Desktop), antworte nur "
    "mit: SKIP"
)
DEFAULT_BLOCK = "30"
BLOCK_PROMPT = (
    "Hier sind Beobachtungen meines Bildschirms von {start} bis {end}, eine alle paar "
    "Minuten. Schreib daraus einen Tagebuch-Eintrag in 1–2 Sätzen aus meiner Sicht "
    "(Ich-Form): woran ich in dieser Zeit gearbeitet habe, mit den konkreten Namen "
    "(Projekte, Repos, Dateien, Apps, Webseiten). Gleiches zusammenfassen, Einmaliges und "
    "Nebensächliches weglassen, nichts dazuerfinden, keine Füllwörter, kein Vorspann. "
    "Wenn nichts Aussagekräftiges dabei ist, antworte nur mit: SKIP\n\n{observations}"
)
DEFAULT_FOLDER = "Clippy"
DEFAULT_TITLE = "Clippy-Tagebuch {date}"


def log(text):
    print(text, file=sys.stderr, flush=True)


# --- Clippy-Host (JSON-RPC über stdio) --------------------------------------

_next_id = 0


def _readline():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    return line.strip()


def call(method, params=None):
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
            if "error" in msg:
                log("RPC-Fehler bei {}: {}".format(method, msg["error"]))
            return msg.get("result")


def notify(method, params):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
    sys.stdout.flush()


def setting(key, default):
    return (call("storage.string", {"key": key, "default": default}) or "").strip() or default


# --- AFFiNE (MCP-Client über stdio) -----------------------------------------

class McpError(Exception):
    pass


class Affine:
    """Kurzlebige Sitzung mit affine-mcp: pro Flush ein Prozess."""

    def __enter__(self):
        npx = shutil.which("npx")
        if not npx:
            raise McpError("npx nicht gefunden, Node.js installieren")
        self.errlog = open(MCP_LOG, "w", encoding="utf-8")  # nur die letzte Sitzung
        self.proc = subprocess.Popen(
            [npx, "-y", "-p", "affine-mcp-server@" + MCP_VERSION, "affine-mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.errlog, text=True, encoding="utf-8", cwd=PLUGIN_DIR,
        )
        self.watchdog = threading.Timer(MCP_TIMEOUT, self.proc.kill)
        self.watchdog.daemon = True
        self.watchdog.start()
        self._id = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "clippy-journal-affine", "version": "0.1.0"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc):
        self.watchdog.cancel()
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self.errlog.close()

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method, params):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise McpError("affine-mcp hat sich beendet, siehe " + MCP_LOG)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != self._id:
                continue
            if "error" in msg:
                raise McpError("{}: {}".format(method, msg["error"].get("message", msg["error"])))
            return msg.get("result") or {}

    def tool(self, tool_name, **args):
        res = self._rpc("tools/call", {"name": tool_name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise McpError("{}: {}".format(tool_name, text))
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def find_key(obj, key):
    """Erstes Vorkommen von ``key`` in verschachteltem JSON (Receipts variieren)."""
    if isinstance(obj, dict):
        if isinstance(obj.get(key), str):
            return obj[key]
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = find_key(child, key)
        if found:
            return found
    return None


def iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_dicts(v)


def ensure_folder(affine, name):
    nodes = affine.tool("list_organize_nodes")
    for node in iter_dicts(nodes):
        if (node.get("type") == "folder" and not node.get("parentId")
                and name in (node.get("data"), node.get("name"))):
            return node["id"]
    created = affine.tool("create_folder", name=name)
    folder_id = find_key(created, "folderId") or find_key(created, "id")
    if not folder_id:
        raise McpError("create_folder ohne id: {}".format(created))
    log("AFFiNE-Ordner '{}' angelegt".format(name))
    return folder_id


def find_day_doc(affine, title):
    res = affine.tool("find_doc_by_title", title=title)
    for match in (res.get("matches") or []) if isinstance(res, dict) else []:
        if not match.get("inTrash"):
            return match["id"]
    return None


# --- Warteschlange & Zustand ------------------------------------------------

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def enqueue(entry):
    with open(QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_queue():
    return read_jsonl(QUEUE_FILE)


def write_queue(entries):
    write_jsonl(QUEUE_FILE, entries)


def flush():
    """Schreibt alle wartenden Einträge nach AFFiNE. Gibt die Anzahl zurück."""
    pending = read_queue()
    if not pending:
        return 0
    folder_name = setting("folder", DEFAULT_FOLDER)
    title_tpl = setting("title", DEFAULT_TITLE)
    state = load_json(STATE_FILE, {})
    days = state.setdefault("days", {})  # Datum -> docId

    dates = sorted({e["date"] for e in pending})
    written = 0
    with Affine() as affine:
        folder_id = None
        for date in dates:
            batch = [e for e in pending if e["date"] == date]
            markdown = "".join("## {}\n\n{}\n\n".format(e["time"], e["text"]) for e in batch)
            title = title_tpl.replace("{date}", date)

            doc_id = days.get(date)
            if doc_id:
                try:
                    affine.tool("append_markdown", docId=doc_id, markdown=markdown)
                except McpError as e:  # Doc gelöscht? Neu suchen bzw. anlegen
                    log("append auf {} fehlgeschlagen ({}), suche neu".format(doc_id, e))
                    doc_id = None
            if not doc_id:
                doc_id = find_day_doc(affine, title)
                if doc_id:
                    affine.tool("append_markdown", docId=doc_id, markdown=markdown)
                else:
                    if folder_id is None:
                        folder_id = ensure_folder(affine, folder_name)
                    created = affine.tool("create_doc_from_markdown", title=title,
                                          markdown=markdown, folderId=folder_id)
                    doc_id = find_key(created, "docId")
                    if not doc_id:
                        raise McpError("create_doc_from_markdown ohne docId: {}".format(created))
                    affine.tool("set_doc_journal", docId=doc_id, date=date)
                    log("Tages-Doc '{}' angelegt ({})".format(title, doc_id))
                days[date] = doc_id

            # Nach jedem Tag sichern: bricht der nächste ab, bleibt nichts doppelt
            for date_old in sorted(days)[:-14]:  # nur die letzten zwei Wochen merken
                del days[date_old]
            save_json(STATE_FILE, state)
            pending = [e for e in pending if e["date"] != date]
            write_queue(pending)
            written += len(batch)
    return written


# --- Eintrag erzeugen -------------------------------------------------------

def read_jsonl(path):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return entries


def write_jsonl(path, entries):
    if entries:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    elif os.path.exists(path):
        os.remove(path)


def observe():
    """Screenshot beschreiben und als Beobachtung lokal ablegen (noch kein Eintrag)."""
    shot = call("vision.capture") or {}
    image = shot.get("image")
    if not image:
        log("vision.capture lieferte kein Bild")
        return

    prompt = setting("prompt", DEFAULT_PROMPT)
    res = call("llm.chat", {"messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image}},
    ]}]})
    if not res or not res.get("content"):
        log("llm.chat ohne Antwort - Modell geladen und multimodal?")
        return

    text = res["content"].strip()
    if not text or text.upper().startswith("SKIP"):
        log("KI meldet 'SKIP' - keine Beobachtung")
        return
    with open(OBS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "text": text},
                           ensure_ascii=False) + "\n")


def condense():
    """Ist der Block um, die Beobachtungen zu einem Eintrag verdichten. True = Eintrag."""
    obs = read_jsonl(OBS_FILE)
    if not obs:
        return False
    try:
        minutes = max(5, int(setting("block", DEFAULT_BLOCK)))
    except ValueError:
        minutes = int(DEFAULT_BLOCK)
    now = datetime.now()
    first = datetime.fromisoformat(obs[0]["at"])
    if (now - first).total_seconds() < minutes * 60:
        return False
    # Ein Block umfasst die eingestellte Zeitspanne ab der ersten Beobachtung und
    # endet spätestens am Tageswechsel (eine Lücke, z. B. Clippy aus, schließt ihn)
    block = []
    for o in obs:
        at = datetime.fromisoformat(o["at"])
        if (at - first).total_seconds() >= minutes * 60 or at.date() != first.date():
            break
        block.append(o)

    start, end = first, datetime.fromisoformat(block[-1]["at"])
    lines = "\n".join("{:%H:%M} {}".format(datetime.fromisoformat(o["at"]), o["text"]) for o in block)
    res = call("llm.chat", {"messages": [{"role": "user", "content": BLOCK_PROMPT.format(
        start="{:%H:%M}".format(start), end="{:%H:%M}".format(end), observations=lines)}]})
    if not res or not res.get("content"):
        log("llm.chat ohne Antwort beim Verdichten, nächster Versuch beim nächsten Trigger")
        return False
    text = res["content"].strip()
    written = bool(text) and not text.upper().startswith("SKIP")
    if written:
        span = "{:%H:%M}".format(start) if start == end else "{:%H:%M}–{:%H:%M}".format(start, end)
        enqueue({"date": "{:%Y-%m-%d}".format(start), "time": span, "text": text})
    else:
        log("Block {:%H:%M}: nichts Aussagekräftiges".format(start))
    write_jsonl(OBS_FILE, obs[len(block):])
    return written


def summarize(prompt):
    res = call("llm.chat", {"messages": [{"role": "user", "content": prompt}]})
    return (res or {}).get("content")


def t3_entries():
    if not call("storage.bool", {"key": "t3", "default": False}):
        return 0
    watcher = t3_threads.Watcher(STATE_DIR)
    entries = watcher.entries(setting("t3Projects", ""), summarize, log)
    for when, text in entries:
        enqueue({"date": "{:%Y-%m-%d}".format(when), "time": "{:%H:%M}".format(when), "text": text})
    return len(entries)


def on_trigger():
    observe()
    new = condense()
    try:
        if t3_entries():
            new = True
    except SystemExit:
        raise
    except Exception as e:  # T3 darf die normalen Einträge nicht blockieren
        log("T3-Fehler: {}".format(e))
    try:
        n = flush()
    except (McpError, OSError, subprocess.SubprocessError) as e:
        log("AFFiNE nicht erreichbar, {} Eintrag/Einträge warten: {}".format(len(read_queue()), e))
        return
    if n:
        log("{} Eintrag/Einträge nach AFFiNE geschrieben".format(n))
        if new and call("storage.bool", {"key": "notify", "default": False}):
            notify("ui.showBubble", {"kind": "journal", "text": "Tagebuch-Eintrag in AFFiNE gespeichert"})


def main():
    if "--flush" in sys.argv:  # von Hand: Warteschlange ohne Clippy leeren (Default-Einstellungen)
        global setting
        setting = lambda key, default: default  # noqa: E731
        print("{} geschrieben".format(flush()))
        return
    while True:
        try:
            msg = json.loads(_readline())
        except json.JSONDecodeError:
            continue
        params = msg.get("params") or {}
        if msg.get("method") == "event" and params.get("topic") == "trigger":
            try:
                on_trigger()
            except SystemExit:
                raise
            except Exception as e:
                log("Journal-Fehler: {}".format(e))


if __name__ == "__main__":
    main()
