# Command contract

Natural language is compiled into these commands; the formal syntax makes work repeatable
(`python scripts/dna.py -f session.dna` replays a script). Every edit command is ONE atomic transaction.

```bash
python <skill-dir>/scripts/dna.py '<command>'
```

## Commands

| Command | Syntax | Effect |
|---|---|---|
| scan | `scan <file> as "<Name>" [suggested]` | intake + persistent template (Step A / pass 1); session → template |
| inspect | `inspect "<T>" aspect <category\|all>` | coverage entry (+ facets, ambiguity) and evidence for one of the 16 categories |
| explain | `explain "<T>" message` | communication chains with status labels |
| reconstruct | `reconstruct "<T>" mode editable\|exact` | render + compare vs reference; first success approves the baseline and pins the renderer; re-runs prove reproducibility |
| migrate-baseline | `migrate-baseline "<T>" [confirm preview=<preview id>]` | preview: render under the current (drifted) environment, compare with the approved baseline + reference and write an immutable `migration-preview.json` (`preview_id`, base revision + model hash, old pin + hash, approved baseline hash, candidate PNG hash, new renderer fingerprint). `confirm preview=<id>` adopts exactly that reviewed candidate; it is refused if anything it was bound to has changed (`stale_preview`, `changed_candidate`), if the id is unknown or already used (`unknown_preview`, `preview_already_confirmed`) or missing (`preview_required`). A legacy pin missing a hard field (`text_rendering`, added in 2.1) is drift that needs this decision, never a silent match |
| use | `use "<T>" for task "<task>" [as "<variant name>"]` | new working variant from the approved model |
| set | `set <path> = <JSON value>` | typed property edit (`"text\nmore"`, `0.16`, `{"policy":"fit"}`) |
| replace | `replace <node>.asset with <file> [preserve treatment,crop-intent,anchor,mask,effects] [baked=cast_shadow]` | new asset, same placement/treatment/mask/effects. In a typed patch, `"source": "generated"` records a synthesized image as generated (default `supplied`) |
| move | `move <node> by x=<n>px y=<n>px` | geometry (+ baseline, + group descendants) |
| resize | `resize <node> to w=<n>px h=<n>px [anchor=center\|top-left…]` | frame size; text size unchanged |
| remove | `remove <node> [force]` | refuses if it backs a slot unless `force` |
| add | `add <node.json> [after <node>]` | inserts a node (marked inferred/added) |
| lock / unlock | `lock <targets> [soft]` · `lock pixels x,y,w,h` · `unlock <target>` | property locks (category or path); pixel locks (region must stay identical in every later render) |
| adapt | `adapt language=ar <node>="…" [font=<file>] [mirror=no]` | content + lang + direction (+ mirrored align, tracking 0, font) |
| reflow | `reflow canvas=<W>x<H> [preserve margins-ratio,reading-order]` | anchored uniform-scale reflow |
| compare | `compare against baseline` | cumulative verification of head vs the approved baseline |
| export | `export formats=png,svg [svg-fonts=embed\|reference]` | PNG + self-contained SVG + element manifest + round-trip verification |
| export-template / import-template | `export-template "<T>" to <dir\|file>` · `import-template <file> [as <id>]` | portable bundles (`references/storage.md`) |
| validate-bundle / bundles / fetch | `validate-bundle <file>` · `bundles <dir>` · `fetch "<T>" from <dir>` | check, list, retrieve-by-id/name + import |
| undo / save | `undo last` · `save as "<name>"` | head → parent revision (files untouched) · name the variant |
| list / find / status / batch | `list [all]` · `find <words>` · `status` · `batch <patch.json>` | index from disk · session · multi-op transaction |

Any edit command may end with **`keep everything else`**.

Lock categories: `layout`, `typography`, `background`, `content`, `color`, `effects`, or any node/path prefix
(`headline`, `headline.geometry`, `hero.effects`, `tokens.accent.primary`).

## "Keep everything else"

1. The ops are compiled first; the **authorised set** = requested paths + their declared dependencies (a move's
   baseline, a token's bound fills, an import's asset record). It is stored in the transaction before any check.
2. Every other leaf property path is **frozen** for this transaction. Any frozen path that changes fails the model
   check; any pixel that changes outside the edited nodes' masks fails the visual check.
3. It adds no persistent locks and removes none. An explicit hard lock covering an authorised path is a conflict
   that names the lock and how to resolve it (`unlock …`); the lock stays.
4. A **relaxable measured relationship** (e.g. the label→headline gap) that the explicit edit necessarily changes is
   relaxed and reported with before/after values. Required (non-relaxable) constraints still conflict.

## Transaction lifecycle (`apply_patch.transact`)

1. Schema-check the patch; refuse a stale `base_revision` (head moved).
2. Apply typed ops to a copy → change records `{path, before, after, kind requested|dependency, why}`.
3. Locks: hard property lock covering a change = conflict; soft lock yields to a requested edit (recorded as
   override) but blocks an unrequested dependency. Pixel locks are checked on the render (step 6).
4. Constraints (mode `adapt` / `reflow`): newly broken = conflict, except relaxations described above.
5. Full validation (schema, hashes, glyph coverage, unsupported features, slot limits, editability).
6. Render base + candidate in the **pinned** browser (drift = `renderer_drift`, nothing committed), then verify:
   - `model_changes`: actual changed paths ⊆ authorised set (frozen-path count reported under keep);
   - `requested_edits`: probed in pixels (moved footprint, fitted text, changed asset pixels, token colour present);
   - `visual_changes` vs the previous revision: influence = union of the edited nodes' alpha masks before + after,
     dilated 2 px, declared before the comparison; 0 changed pixels allowed outside it; per-node attribution and
     compositing consequences listed; a background edit = whole-canvas influence, disclosed;
   - `vs_approved_baseline` (from the second edit on): the same model + visual checks for **everything authorised
     since the variant began**, against the approved template baseline image;
   - `pixel_locks`: changed pixels inside each locked region (must be 0);
   - `reflow_preserve` instead of pixel checks when the canvas changes.
7. Commit immutable `rev-NNNN.json` + `txn-NNNN.json`, move the head. Any failure → `rejected/` record, head
   unchanged, options returned. Undo moves the head back; history is never rewritten.

## Mandatory edit behaviour

- Resolve aliases to ids; ambiguity → ask (the error lists candidates).
- Unsupported property/effect/adapter → reject with the reason; never accept-and-ignore.
- Fitting: `strict` reports overflow with options (shorten, enlarge box, add line, allow size range);
  `fit` shrinks only to `fit.min_size`. Nothing is silently shrunk or clipped.
- Goal/theme/character/message changes are semantic: state the copy/image/hierarchy/CTA implications and ask only
  about unresolved material choices.
- Property locks ≠ pixel locks: a changed backdrop changes translucent pixels even with locked properties.
