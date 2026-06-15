# Ein Plugin einreichen

Danke, dass du Clippy erweitern willst! Plugins kommen per **Pull Request** in den
Katalog — das ist die Kuratierung.

## Voraussetzungen

- Dein Plugin folgt dem Leitfaden
  [writing-plugins.md](https://github.com/shipbit/clippy/blob/master/docs/writing-plugins.md).
- **WASM bevorzugt** (läuft sandboxed). Sidecar-Plugins (eigener Prozess, volle
  Rechte) werden aufgenommen, aber in Clippy deutlich markiert — begründe im PR,
  warum kein WASM möglich ist.
- Das Manifest `clippy.plugin.json` ist vollständig: `id` (reverse-DNS, eindeutig),
  `name`, `version` (SemVer), `hostApi`, `runtime`, `permissions`. Empfohlen:
  `description`, `author`, `homepage`, `icon`.

## Schritte

1. Lege deinen Plugin-Ordner unter `plugins/<ordner>/` ab (Manifest + Dateien).
2. Optional `plugins/<ordner>/store.json` für die Kuratierung:
   ```json
   { "tags": ["produktivität"], "recommended": false }
   ```
   (`store.json` landet **nicht** im ausgelieferten Zip.)
3. **`dist/` und `index.json` nicht selbst committen** — die erzeugt die CI
   verbindlich beim Merge (lokale Builds können sich durch zlib/Plattform
   unterscheiden). Lokal nur zum Prüfen: `npm install && npm run build`.
4. Pull Request öffnen. Im Review schauen wir auf Manifest, Permissions (so wenige
   wie möglich), Runtime und — bei Sidecar — auf den Quellcode.

## Versionen & Updates

- Neue Version = `version` im Manifest erhöhen (SemVer). Clippy erkennt das und
  bietet (bzw. installiert bei aktivem Auto-Update) die neue Version an.
- Die `id` bleibt über Versionen stabil.
