# Contributing to Design DNA

Thanks for helping. Design DNA has one rule above all others: **never let the engine claim more than the
evidence supports.** Every contribution is reviewed against that.

## Ground rules

1. **Measured, inferred, unknown stay separate.** A new measurement writes an evidence record (`common.add_evidence`)
   with method, tool version, status and confidence. Guesses are `inferred`; missing evidence is `unknown`.
2. **Unknown is never a pass.** New checks return `pass | fail | unknown`.
3. **No silent fallbacks.** Unsupported features are rejected with a reason (`validate_model.SUPPORTED`).
4. **Nothing is deleted.** Revisions, sources and assets are immutable; undo moves a pointer.
5. **Determinism.** Rendering stays pinned (DPR 1, sRGB, fonts from files, seeded randomness).

## Development setup

```bash
git clone https://github.com/OzyAcc/design-dna
cd design-dna
python -m pip install -r requirements.txt pyflakes
python skills/reverse-design/scripts/capabilities.py
```

## Before you open a pull request

```bash
python -m pyflakes skills/reverse-design/scripts skills/reverse-design/tests
python skills/reverse-design/tests/run_acceptance.py          # ~30 min; Windows system fonts, or tests/fonts elsewhere
python skills/reverse-design/tests/run_acceptance.py --only 4,6   # a subset while iterating
```

Every acceptance check in `report.md` must pass. Entries marked `unverified` stay unverified until a real test
replaces them. If you add a capability, add a demonstration that exercises it and keeps its inputs and outputs.
List the capability in `references/adapters.md` and `CAPABILITIES.md`.

## Adding an adapter (PDF, layered source, UI, motion …)

Keep the same evidence and scene contracts: an intake path that writes `source/` + evidence, a capability entry in
`scripts/capabilities.py`, renderer support or an explicit `unsupported` validation entry, and at least one
acceptance test. "Supported" means demonstrated, not planned.

## Style

- Python 3.10+, standard library first, small functions, files under 500 lines.
- Match the surrounding code; comments explain *why*.
- Reference docs live in `skills/reverse-design/references/`; keep `SKILL.md` short.

## Reporting bugs

Use the issue templates. Attach the `report.json` of the failing comparison or the rejected transaction
(`variants/<id>/rejected/*.json`): they contain the evidence needed to reproduce.
