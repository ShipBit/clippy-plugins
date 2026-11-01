# Tagebuch in AFFiNE

Variante von [journal-cam](../journal-cam/): Alle 5 Minuten (Intervall in Clippy
einstellbar) ein Screenshot, die lokale KI beschreibt, woran du arbeitest. Der
Eintrag landet in [AFFiNE](https://affine.pro) (selbst gehostet oder Cloud):

- ein Doc pro Tag (`Clippy-Tagebuch JJJJ-MM-TT`), als natives AFFiNE-**Journal**
  für das Datum markiert,
- im Ordner `Clippy` der Seitenleiste (wird angelegt, falls er fehlt),
- jeder Eintrag als `## HH:MM` plus Text angehängt.

Optional fasst die KI gesettlete Threads aus [T3 Code](https://t3.codes)
zusammen (Einstellung „T3-Code-Threads zusammenfassen“, siehe `t3_threads.py`).

## Voraussetzungen

- ein multimodales Modell in Clippy,
- Node.js (`npx`): AFFiNE wird über den Community-MCP-Server
  [`affine-mcp-server`](https://github.com/DAWNCR0W/affine-mcp-server) angesprochen
  (Version im Plugin gepinnt). Die eingebauten MCP-Schreibtools von AFFiNE sind
  in Stable-Builds gesperrt.
- einmalig anmelden und den Workspace wählen:

  ```sh
  npx -y -p affine-mcp-server@3.10.2 affine-mcp login --save-credentials
  ```

  Bei selbst gehostetem AFFiNE E-Mail/Passwort wählen. Die Zugangsdaten liegen in
  `~/.config/affine-mcp/config` (Modus 600), nicht im Plugin. Wer das Passwort dort
  nicht ablegen will, nimmt ein eigenes AFFiNE-Konto für Clippy und lädt es in den
  Workspace ein.

## Betrieb

- Warteschlange und Zustand liegen in `~/.local/state/clippy-journal-affine/`
  (Windows: `%LOCALAPPDATA%\clippy-journal-affine\`): `queue.jsonl`, `state.json`,
  `t3.json` und `affine-mcp.log` der letzten Sitzung. Ist AFFiNE nicht erreichbar,
  bleiben die Einträge in der Queue und gehen beim nächsten Trigger raus.
- Von Hand nachliefern: `python journal_affine.py --flush` (nutzt die
  Default-Einstellungen).
