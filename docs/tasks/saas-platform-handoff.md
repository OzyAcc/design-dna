# SaaS platform and library pipeline — coordination handoff

This branch coordinates a separate follow-up task. It does not replace the active dashboard work.

## Reviewed starting points

- Public core: `main` at `eb7f1325f923b2a41f0c29ff3bb2ed180fc18ef2`.
- Dashboard snapshot: `claude/eager-gauss-j1fccc` at `0c3d3cb71e8bbb4b22ee389451bf678eea82aa74`. Work is ongoing; review the latest version before integration.
- Preserve both histories and integrate reviewed changes before implementation.

## Two separate assignments

1. **SaaS platform:** build the hosted product layer around the reviewed dashboard, including individual accounts, workspace authorization, subscription entitlements, and secure managed execution.
2. **Library pipeline:** build manual curation and permitted-source discovery as a later task after the platform contracts are ready.

Read the owner-provided private **Design-DNA-SaaS-and-Library-Claude-Build-Spec.md** for detailed outcomes, commercial requirements, delivery gates, and acceptance criteria. The full brief is intentionally not published in this public repository.

Keep the public core's licence and notices. Commercial implementation, the private catalogue, and secrets belong in a private commercial repository, not this coordination branch. Do not begin automated collection without source authorization, or activate paid services or production deployment from this handoff.

Start with the SaaS assignment in the private brief. Keep the library assignment separate until its prerequisites pass.
