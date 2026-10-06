# Command contract

Natural language is compiled into these commands; the formal syntax makes work repeatable
(`python scripts/dna.py -f session.dna` replays a script). Every edit command is ONE transaction.

```bash
python <skill-dir>/scripts/dna.py '<command>'
```

## Commands

| Command | Syntax | Effect |
|---|---|---|
| scan | `scan <file> as "<Name>" [suggested]` | intake + persistent template (Step A/pass 1); session → template |
| inspect | `inspect "<T>" aspect <category\|all>` | coverage entry + evidence for one of the 16 categories |
| explain | `explain "<T>" message` | communication chains with status labels |
| reconstruct | `reconstruct "<T>" mode editable\|exact` | render baseline (PNG + SVG), compare vs canonical, update readiness |
| use | `use "<T>" for task "<task>" [as "<variant name>"]` | new working variant from the baseline; inherits limitations |
| set | `set <path> = <JSON value>` | typed property edit (`"text\nmore"`, `0.16`, `{"policy":"fit"}`) |
| replace | `replace <node>.asset with <file> [preserve treatment,crop-intent,anchor] [baked=cast_shadow]` | new asset, same placement/treatment/mask/effects |
| move | `move <node> by x=<n>px y=<n>px` | geometry (+ baseline, + group descendants) |
| resize | `resize <node> to w=<n>px h=<n>px [anchor=center\|top-left…]` | frame size; text size unchanged |
| remove | `remove <node> [force]` | refuses if it backs a slot unless `force` |
| add | `add <node.json> [after <node>]` | inserts a node (marked inferred/added) |
| lock / unlock | `lock layout,typography,background [soft]` · `unlock <target>` | hard locks block; soft locks yield to explicit edits |
| adapt | `adapt language=ar <node>="…" [font=<file>] [mirror=no]` | content + lang + direction (+ mirrored align, tracking 0, font) |
| reflow | `reflow canvas=<W>x<H> [preserve margins-ratio,reading-order]` | anchored uniform-scale reflow |
| compare | `compare against baseline` | cumulative verification of head vs variant baseline |
| export | `export formats=png,svg` | render head to `exports/rev-NNNN/` |
| undo | `undo last` | head → parent revision (files untouched) |
| save | `save as "<name>"` | names the variant |
| list / find | `list [all]` · `find <words>` | index from disk |
| batch | `batch <patch.json>` | multi-op transaction (`patch.schema.json`) |
| status | `status` | session + head + recent history |

Lock categories: `layout`, `typography`, `background`, `content`, `color`, `effects`, or any path prefix
(`headline`, `hero.effects`, `tokens.accent.primary`).

## Transaction lifecycle (`apply_patch.transact`)

1. Schema-check the patch; refuse a stale `base_revision` (head moved).
2. Apply typed ops to a copy; each op returns change records `{path, before, after, kind requested|dependency, why}`.
   Dependencies are explicit: token → every bound node; move → baseline + group descendants; replace → aspect/crop
   note; adapt → lang, direction, mirrored align, tracking 0, font + identity; reflow → every scaled property.
3. Locks: hard lock covering a change = conflict (`unlock …` to resolve); soft lock yields to a requested edit
   (recorded as override) but blocks an unrequested dependency.
4. Constraints (mode `adapt` or `reflow`): newly broken = conflict unless `relax:[id]` on a relaxable constraint.
5. Full scene validation (schema, assets/hashes, glyph coverage, unsupported features, editability).
6. Render base + candidate (isolated per-node bounds) and verify:
   - property check: actual changed paths ⊆ declared changes (no unrequested drift);
   - requested edits probed in the render (moved bounds, fitted text, changed asset pixels, new token colour present);
   - `adapt_preserve`: expected influence = before/after rendered bounds of affected nodes (declared before the pixel
     check); zero changed pixels outside it; translucent/blended nodes over changed regions reported as compositing
     consequences; background change = whole-canvas influence → property checks only, disclosed;
   - `reflow_preserve`: target dims, reading order, nothing off-canvas, no new overlaps, text fit.
7. Commit immutable `rev-NNNN.json` + `txn-NNNN.json`, move head. Any failure → `rejected/` record, head unchanged,
   options returned.

## Mandatory edit behaviour

- Resolve aliases to ids; ambiguity → ask (the error lists candidates).
- Unsupported property/effect/adapter → reject with the reason; never accept-and-ignore.
- A specific edit authorises that property; "keep X" means soft-preserve; explicit hard locks conflict.
- Narrow edits keep everything else locked by construction (property check).
- Fitting: `strict` reports overflow with options (shorten, enlarge box, add line, allow size range);
  `fit` shrinks only to `fit.min_size`. Nothing is silently shrunk or clipped.
- Goal/theme/character/message changes are semantic: state the copy/image/hierarchy/CTA implications and ask only
  about unresolved material choices.
- Property locks ≠ pixel locks: a changed backdrop changes translucent pixels even with locked properties.
