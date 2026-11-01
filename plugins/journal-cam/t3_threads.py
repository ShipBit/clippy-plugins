"""T3 Code: gesettlete Threads finden und als Tagebuch-Eintrag zusammenfassen.

Gemeinsames Modul von journal-cam und journal-affine (identische Kopie in beiden
Plugin-Ordnern, weil jedes Plugin als eigenes Zip ausgeliefert wird; bei
Änderungen beide anpassen).

T3 Code hat keine Hooks für fremde Programme. Das Modul fragt deshalb bei jedem
Trigger die offizielle ``t3``-CLI ab (``t3 thread list/show --json``, braucht
eine laufende T3-App) und merkt sich, welche Settles schon im Tagebuch stehen.
Die CLI kann Projekte nicht auflisten; welche Ordner abgefragt werden, steht in
der Plugin-Einstellung ``t3Projects`` (Globs, ein Ordner kann zu einem
übergeordneten Projekt gehören, doppelte Projekte werden zusammengefasst).
"""
import glob
import json
import os
import shutil
import subprocess
from datetime import datetime

DEFAULT_PROJECTS = "~, ~/Developer/*, ~/Projects/*"
MAX_CHARS = 16000  # Transkript-Budget für das lokale Modell
MAX_MESSAGES = 200
PROMPT = (
    "Hier ist das Protokoll einer Arbeitssitzung mit einem Coding-Agenten in T3 Code "
    "(Projekt: {project}, Thread: {title}). Ich habe den Thread gerade als erledigt "
    "markiert. Fasse für mein Tagebuch in 2–4 Sätzen in der Ich-Form zusammen, was ich "
    "erreichen wollte, was dabei herauskam und was offen geblieben ist. Sachlich, keine "
    "Aufzählung, kein Vorspann.\n\n{transcript}"
)


def state_dir(name):
    """Plattformüblicher Ort für Plugin-Zustand, der Updates des Plugin-Ordners überlebt."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


def t3_binary():
    # Zuerst den Starter, den die Desktop-App pflegt: er läuft immer mit deren
    # Version. Ein ``t3`` im PATH kann eine ältere Standalone-Version sein.
    for candidate in ("~/.t3/bin/t3", "~/.t3/bin/t3.cmd"):
        path = os.path.expanduser(candidate)
        if os.path.exists(path):
            return path
    return shutil.which("t3")


def _t3(args, timeout=30):
    out = subprocess.run([t3_binary()] + args, capture_output=True, text=True,
                         encoding="utf-8", timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:300])
    return json.loads(out.stdout)


def project_dirs(spec):
    dirs = []
    for pattern in (p.strip() for p in (spec or DEFAULT_PROJECTS).split(",")):
        if pattern:
            dirs += sorted(d for d in glob.glob(os.path.expanduser(pattern)) if os.path.isdir(d))
    return dirs


def settled_threads(spec):
    """Alle gesettleten Threads der konfigurierten Projekte (ohne Subagent-Threads)."""
    threads, projects = {}, set()
    for d in project_dirs(spec):
        try:
            listed = _t3(["thread", "list", "--json", "--project", d])
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
            continue  # kein T3-Projekt bzw. T3 läuft nicht
        if not listed or listed[0]["projectId"] in projects:
            continue  # Ordner gehört zu einem schon abgefragten Projekt
        projects.add(listed[0]["projectId"])
        name = os.path.basename(os.path.normpath(d))
        for t in listed:
            if t.get("settled") and t.get("settledAt") and not t.get("parentThreadId"):
                t["projectName"] = name
                threads[t["threadId"]] = t
    return list(threads.values())


def transcript(thread_id):
    """Erste Nachricht (das Ziel) plus so viel vom Ende, wie ins Budget passt."""
    msgs = _t3(["thread", "show", thread_id, "--messages", str(MAX_MESSAGES), "--json"])["messages"]
    turns = ["{}: {}".format("Ich" if m["role"] == "user" else "Agent", m["text"].strip())
             for m in msgs if m.get("role") in ("user", "assistant") and (m.get("text") or "").strip()]
    if not turns:
        return ""
    head, tail, size = turns[0][:4000], [], 0
    for t in reversed(turns[1:]):
        t = t[:3000]
        if size + len(t) > MAX_CHARS - len(head):
            break
        tail.insert(0, t)
        size += len(t)
    skipped = len(turns) - 1 - len(tail)
    gap = ["[… {} Nachrichten ausgelassen …]".format(skipped)] if skipped else []
    return "\n\n".join([head] + gap + tail)


def local_time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


class Watcher:
    """Merkt sich in ``<state>/t3.json``, welche Settles schon verarbeitet sind."""

    def __init__(self, directory):
        self.path = os.path.join(directory, "t3.json")

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save(self, seen):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"seen": seen}, f, indent=1)
        os.replace(tmp, self.path)

    def entries(self, spec, summarize, log):
        """Fasst neue Settles zusammen und liefert ``(datetime, markdown)``-Einträge.

        ``summarize(prompt) -> str`` fragt die KI. Beim ersten Lauf werden nur
        Settles von heute übernommen, nicht die ganze Historie. Liefert die KI
        nichts, bleibt der Thread offen und kommt beim nächsten Trigger dran.
        Wird ein Thread erneut gesettled, gibt es einen neuen Eintrag.
        """
        if not t3_binary():
            return []
        state = self._load()
        seen = (state or {}).get("seen", {})
        today = datetime.now().date()
        out = []
        for t in sorted(settled_threads(spec), key=lambda t: t["settledAt"]):
            if seen.get(t["threadId"]) == t["settledAt"]:
                continue
            when = local_time(t["settledAt"])
            if state is None and when.date() != today:
                seen[t["threadId"]] = t["settledAt"]
                continue
            text = transcript(t["threadId"])
            summary = (summarize(PROMPT.format(project=t["projectName"], title=t["title"],
                                               transcript=text)) or "").strip() if text else ""
            if text and not summary:
                log("T3: keine Zusammenfassung für '{}', nächster Versuch beim nächsten Trigger".format(t["title"]))
                break
            seen[t["threadId"]] = t["settledAt"]
            if summary:
                prs = " · ".join("[PR #{}]({})".format(p["number"], p["url"])
                                 for p in t.get("pullRequests") or [] if p.get("url"))
                head = "**T3 Code · {} · [{}]({})**".format(t["projectName"], t["title"], t["link"]) \
                    if t.get("link") else "**T3 Code · {} · {}**".format(t["projectName"], t["title"])
                out.append((when, head + ("\n\n" + prs if prs else "") + "\n\n" + summary))
        self._save(seen)
        return out
