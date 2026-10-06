# Storage: working store, portable bundles, host persistence

The engine reads and writes one **working store** (`~/design-dna`, or `DESIGN_DNA_HOME`). It is a cache: a template
that only lives there dies with the folder. Persistence is the **bundle**: one immutable `.dnab` file per export,
kept in any persistent storage the host provides.

## Bundle format (`.dnab` = ZIP)

```text
manifest.json            schemas/bundle.schema.json — id, name, aliases, readiness, renderer pin, approved baseline,
                         fonts (sha256 + names + embedded|referenced), variants (head + revisions), files (path, sha256, bytes)
template/passport.json   name, character, goal, theme, uses, message, mechanism, readiness, pin, migrations, imports
template/scene.json      the approved model (nodes, tokens, assets, slots, constraints, locks, coverage, communication)
template/source/         original reference bytes + canonical sRGB copy + thumbnail
template/assets/         content-hashed images, masks and (unless --fonts reference) font files
template/evidence/       evidence.json, crops, contact sheets, annotated scan, scan_report.md
template/baseline/       every baseline run: approved render, SVG export + manifest, comparison reports, migrations
template/variants/<id>/  variant.json, revisions/rev-NNNN.json, transactions/txn-NNNN.json, rejected/*.json
```

Excluded: render caches (`variants/*/renders`), exports and `.render` scratch — all re-creatable.

## Operations (`scripts/bundle.py`, also via `dna.py`)

| Command | Behaviour |
|---|---|
| `export-template "<T>" to <dir \| file.dnab> [fonts=reference]` | writes `<id>@<timestamp>[-fontref].dnab`; never overwrites |
| `validate-bundle <file> [font-dir=<dir>]` | manifest schema, path safety, every hash, unlisted/missing files, referenced fonts resolvable, scene + passport + evidence valid, approved baseline intact, every variant's revision chain intact |
| `import-template <file> [as <id>] [font-dir=<dir>]` | validates first, writes nothing on failure; same id + identical files = no-op; same id + different files = `id_collision` (use `as <id>`); referenced fonts are copied in after their hash matches |
| `bundles <dir>` / `fetch "<id \| name \| alias>" from <dir>` | library listing; retrieval by stable id, name or alias (newest export wins, ambiguity is an error) |

Fonts: `embed` (default) makes the bundle self-sufficient — check the font licences before sharing it.
`reference` stores only names, sizes and sha256; import resolves them from `--font-dir` and the platform font
folders by hash (never by name). Without a matching file, validation fails and says which font is missing.

## Host persistence seam

`bundle.StorageBackend` is three methods: `put(name, bytes)`, `get(name) -> bytes`, `list() -> [names]`.

- `FilesystemBackend(root)` — implemented and tested (acceptance T20): any mounted persistent folder works.
- A host file store without a mounted folder (for example ChatGPT Work's persistent storage, if it is only
  reachable through an API) needs a small adapter implementing the same three methods. **That integration is
  UNVERIFIED in this package** (acceptance entry 23): no such host was available to test against.

Rule of thumb for any host: after a scan, after a reconstruct and after each saved variant, export a bundle to the
persistent store; at the start of a session, `fetch` the template you need into the (possibly empty) working store.
