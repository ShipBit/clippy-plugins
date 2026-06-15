# clippy-plugins

Kuratierter **Plugin-Katalog** für [Clippy](https://github.com/shipbit/clippy) —
das Backend des In-App-Stores (Einstellungen → Store). Clippy lädt von hier
`index.json` und installiert Plugins mit einem Klick.

## Wie es funktioniert

- Jedes Plugin liegt als Quelle unter `plugins/<ordner>/` (mit `clippy.plugin.json`
  + Dateien, optional `store.json` für Kuratierung).
- Der Maintainer baut den Katalog mit `npm run build` (erzeugt `dist/<id>-<version>.zip`
  + `index.json` mit SHA256) und committet das Ergebnis.
- Clippy lädt `index.json` von
  `https://raw.githubusercontent.com/ShipBit/clippy-plugins/main/index.json`
  und die Zips aus `dist/` (per `raw.githubusercontent`).

### CI optional aktivieren
Eine fertige GitHub-Action liegt unter `ci/build.workflow.yml` (baut + committet bei
jeder Änderung automatisch). Aktivieren: nach `gh auth refresh -h github.com -s workflow`
die Datei nach `.github/workflows/build.yml` verschieben und pushen (das Pushen von
Workflows braucht den `workflow`-Token-Scope).

## Vertrauensmodell

- **Kuratierung:** Aufnahme nur per Pull Request (Review von Manifest,
  Permissions, Runtime). **WASM bevorzugt** (sandboxed); Sidecar-Plugins werden
  in Clippy als „volle Rechte" markiert.
- **Integrität:** Clippy prüft die SHA256 des Zips gegen `index.json`.
- **Einwilligung:** Clippy zeigt vor der Installation die Permissions im Klartext.

Details zum Format: [docs/app-store.md im Hauptrepo](https://github.com/shipbit/clippy/blob/master/docs/app-store.md).

## Lokal bauen

```bash
npm install
npm run build        # erzeugt dist/*.zip + index.json
```

Zum Testen gegen eine lokale Clippy-Instanz: Ordner servieren
(`python -m http.server 8000`) und in Clippys `settings.json`
`"pluginStoreUrl": "http://127.0.0.1:8000/index.json"` setzen sowie
`CATALOG_BASE_URL=http://127.0.0.1:8000/dist npm run build`, damit die
`downloadUrl`s auf den lokalen Server zeigen.

## Ein Plugin einreichen

Siehe [CONTRIBUTING.md](CONTRIBUTING.md).
