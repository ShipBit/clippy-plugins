#!/usr/bin/env node
// Baut aus plugins/<ordner>/ je ein Zip nach dist/ und erzeugt index.json.
//
// Jede Plugin-Quelle ist ein Ordner mit clippy.plugin.json (+ Dateien) und
// optional store.json (Kuratierung: { tags, recommended }). Das Zip enthält die
// Plugin-Dateien im Wurzelverzeichnis (store.json wird ausgeschlossen). Die
// Katalog-Metadaten kommen aus dem Manifest, SHA256/Größe aus dem Zip.
import { createHash } from "node:crypto";
import {
  readFileSync,
  writeFileSync,
  readdirSync,
  statSync,
  mkdirSync,
  createWriteStream,
  rmSync,
} from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import archiver from "archiver";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PLUGINS_DIR = join(ROOT, "plugins");
const DIST_DIR = join(ROOT, "dist");
// Basis-URL der Zips. Muss zum Hosting passen (raw.githubusercontent des Repos).
const BASE_URL =
  process.env.CATALOG_BASE_URL ??
  "https://raw.githubusercontent.com/ShipBit/clippy-plugins/main/dist";

// Fester Zeitstempel für alle Zip-Einträge → deterministische Zips (gleiche
// Eingabe ⇒ gleiche SHA256), sonst baut die CI bei jedem Lauf neue Hashes.
const FIXED_DATE = new Date("2020-01-01T00:00:00Z");

function zipDir(srcDir, outFile) {
  return new Promise((resolve, reject) => {
    const output = createWriteStream(outFile);
    const archive = archiver("zip", { zlib: { level: 9 } });
    output.on("close", resolve);
    archive.on("error", reject);
    archive.pipe(output);
    // Plugin-Dateien ins Zip-Wurzelverzeichnis; Kuratierungs-Metadaten raus.
    archive.glob("**/*", { cwd: srcDir, ignore: ["store.json"], dot: false }, { date: FIXED_DATE });
    archive.finalize();
  });
}

const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

async function main() {
  rmSync(DIST_DIR, { recursive: true, force: true });
  mkdirSync(DIST_DIR, { recursive: true });

  const dirs = readdirSync(PLUGINS_DIR).filter((d) =>
    statSync(join(PLUGINS_DIR, d)).isDirectory(),
  );

  const entries = [];
  for (const name of dirs.sort()) {
    const dir = join(PLUGINS_DIR, name);
    const manifest = JSON.parse(readFileSync(join(dir, "clippy.plugin.json"), "utf8"));
    let store = { tags: [], recommended: false };
    try {
      store = { ...store, ...JSON.parse(readFileSync(join(dir, "store.json"), "utf8")) };
    } catch {
      // store.json ist optional
    }

    const zipName = `${manifest.id}-${manifest.version}.zip`;
    const zipPath = join(DIST_DIR, zipName);
    await zipDir(dir, zipPath);
    const sizeBytes = statSync(zipPath).size;

    entries.push({
      id: manifest.id,
      name: manifest.name,
      description: manifest.description ?? {},
      author: manifest.author ?? "shipbit",
      homepage: manifest.homepage ?? "https://github.com/ShipBit/clippy-plugins",
      icon: manifest.icon ?? manifest.contributes?.settingsSection?.icon,
      version: manifest.version,
      runtime: manifest.runtime,
      permissions: manifest.permissions ?? [],
      minHostApi: manifest.hostApi,
      downloadUrl: `${BASE_URL}/${zipName}`,
      sizeBytes,
      sha256: sha256(zipPath),
      tags: store.tags,
      recommended: store.recommended,
    });
    console.log(`✓ ${manifest.id} v${manifest.version} (${sizeBytes} B)`);
  }

  // Empfohlene zuerst, dann alphabetisch (englischer Name als Schlüssel).
  entries.sort(
    (a, b) =>
      Number(b.recommended) - Number(a.recommended) ||
      String(a.name.en ?? a.id).localeCompare(String(b.name.en ?? b.id)),
  );

  writeFileSync(join(ROOT, "index.json"), JSON.stringify(entries, null, 2) + "\n");
  console.log(`\nindex.json: ${entries.length} Einträge`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
