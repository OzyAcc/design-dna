# Design DNA instruction kit (v{{VERSION}}): a fallback, not a skill

Use this kit only where the native skill cannot run: ChatGPT Free, Plus or Pro (Projects or custom GPTs), or a
workspace without Skills, and any other assistant that accepts custom instructions but cannot run code.

| File | Where it goes |
|---|---|
| `INSTRUCTIONS.md` | The assistant's instructions field (fits ChatGPT's 8,000-character custom GPT limit) |
| `knowledge/design-dna-skill.md` | Knowledge or reference files: the full method |
| `knowledge/design-dna-*.md` | Knowledge files: scan, scene model, commands, fidelity, adapters and storage contracts |
| `knowledge/design-dna-*.schema.json` | Knowledge files: the data formats for templates, evidence, patches and bundles |

## What you get, and what you don't

| Feature | Instruction kit | Native skill with Python + Chromium |
|---|---|---|
| Scan method, 16 categories, evidence statuses, honest claims | yes | yes |
| Measured geometry, colours, shadows, text metrics | no: visual estimates, labelled `inferred` | yes |
| Font candidates | named by eye; identity always unknown | ranked by rendering the supplied font files |
| Rebuild and pixel or region verification | no | yes |
| "Change only X, keep everything else" | a JSON change list, not verified in pixels | verified against the previous revision and the approved baseline |
| Saved templates | the JSON you keep and paste back | template store plus portable `.dnab` bundles |

The assistant is told to start such answers with an instruction-only label. If you need measured, verified
results, install the native skill: https://github.com/OzyAcc/design-dna#choose-your-ai-tool
