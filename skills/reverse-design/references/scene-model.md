# Scene model, template passport, store layout

Schemas: `schemas/scene.schema.json` (model), `template.schema.json` (passport), `evidence.schema.json`,
`patch.schema.json`. Version `1.0.0`; a future version adds a migration in `common.py` and bumps `schema_version`.

## Store layout (outside the skill; default `~/design-dna`, override `DESIGN_DNA_HOME`)

```text
design-dna/
  index.json                      rebuilt by index_templates.py (name, aliases, readiness, aspect, character…)
  session.json                    current template + variant for dna.py
  templates/<template-id>/
    source/<sha16>.<ext>          original bytes, immutable;  canonical.png = sRGB comparison copy; thumb.png
    assets/<sha16>.<ext>          content-hashed fonts / images / masks (immutable)
    evidence/evidence.json        evidence records; crops/, fonts/ contact sheets; annotated.png; scan_report.md
    passport.json                 template identity + readiness
    scene.json                    the baseline model (revision N)
    baseline/rev-NNNN/            baseline.png + baseline.svg master + assets/ + compare/ (metric panel, heatmap, crops)
    variants/<variant-id>/
      variant.json                name, task, head, revision list, history, inherited limitations
      revisions/rev-NNNN.json     immutable scene per committed revision (base_revision = parent)
      transactions/txn-NNNN.json  ops, change records, locks/constraints results, verification
      rejected/txn-<time>.json    rejected transactions with conflicts + options
      renders/<scene-hash>/       render cache keyed by scene content (never reused for another scene)
      exports/rev-NNNN/           PNG + SVG master + assets + scene.json
```

## Scene (top level)

| Key | Contents |
|---|---|
| `source` | sha256, original path/name, metadata, canonical copy + conversion |
| `canvas` | width, height, origin `top-left`, units `px`, `color_space: srgb`, `alpha`, background composite |
| `tokens` | role → `{type, value, space, status, confidence, evidence_ids, samples, sample_method}` |
| `assets` | id → `{path, sha256, kind, source, width/height, derived_from, baked_effects, font_names}` |
| `nodes` | paint order back→front for root nodes; groups order their `children` |
| `constraints` | `{id, type: gap/anchor/equal/ratio/range, a, b, value/min/max, tolerance, priority, modes, relaxable}` |
| `slots` | replaceable roles: `{id, role, node, type: text/image/color/logo/shape, limits, fit, treatments_allowed}` |
| `communication` | goal, literal_message, takeaway, cta, word_image_relationship, mechanisms[], hierarchy |
| `locks` | `{id, target, kind: property/relationship/asset/pixel, hard}` |
| `scan` | `state` + `coverage` (16 categories) |
| `verification` | tolerances (declared before iteration), expected_text (transcription), report paths |
| `variant` | set on variant revisions: variant id, base revision, task |

## Nodes

Common: `id` (stable), `alias`, `type`, `role`, `parent`, `geometry {x,y,w,h,rotation}`, `transform`, `visible`,
`opacity`, `blend`, `effects[]`, `editability` (`live | raster | outlined | unknown`), `provenance` (per property
path or `*`: status, confidence, evidence_ids, alternatives, resolving_probe, note), `reflow {x,y}` anchors.

| Type | Specific fields |
|---|---|
| `background` | `fill` paint or `asset` + `placement` |
| `shape` | `shape: rect/ellipse`, `radius`, `fill`, `stroke {color,width,align:center}` |
| `path` | `path` (d), `path_box [w,h]`, fill/stroke |
| `text` | `content`, `font {asset, family, weight, size, features, variation, horizontal_scale, synthetic, identity}` or `font.token`, `align`, `direction`, `lang`, `first_baseline`, `line_height`, `tracking`, `fill`, `fit {policy strict/fit, min_size, max_lines}` |
| `image` | `asset`, `placement {fit cover/contain/fill/none, focal [fx,fy], scale, crop}`, `mask`, `treatment[]` |
| `group` | `children` (ordered ids) |
| `effect` | `effect {kind: grain (seeded feTurbulence) / vignette}` |

Paint = `#RRGGBB[AA]` | `{"token": key}` | gradient `{type linear/radial, stops, units canvas/node, interpolation srgb}`.
Font identity: `{"status": "unknown", "candidates": [...], "evidence_ids": [...], "resolving_probe": "..."}`
— an unknown font may still render through a pinned candidate file; the identity field stays unknown.

## Property addressing (used by `set`, locks, change records)

- `tokens.<role>` → token value (longest matching role key; roles may contain dots), `tokens.<role>.<field>`.
- `<node id | alias | unique role>.<prop>[.<sub>…]` → e.g. `headline.content`, `hero.effects.cast_shadow.opacity`,
  `hero.placement.focal`. List items are addressed by `id`, `type` or `op`, or index.
- Normalised form in reports: `nodes.<id>.<path>`. Ambiguous alias = error with candidates (never a guess).

## Template passport (`passport.json`)

id, name (+ `name_status`: user_supplied / suggested / user_confirmed), aliases, thumbnail, reference, revision,
**readiness**, character, theme, goal, literal_message, takeaway, mechanism, medium, channels, usage,
unsuitable_for, audience_assumptions (each `{value, status}`; Claude's guesses are `suggested`/`inferred`),
visual_signature, aspect_ratio, slots, constraints_summary, editability_coverage, unresolved, baseline_match
`{profile, status, report, how: copying|asset_reuse|editable_rendering|mixed}`, brand_association (only when the
user supplies it), fixture flag.

Readiness = the highest level the saved baseline actually passed:
`scan_in_progress → scanned → partial_baseline (rendered, failed or incomplete) → editable_close → exact_pixels`.
Every scan — partial ones included — persists as a named template. Recall loads files; never rebuild from memory.

House or client brands are never applied to a reference unless the task says so; brand mapping is a
separate adaptation, not a scan finding.
