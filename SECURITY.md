# Security policy

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** (Security → Report a vulnerability) rather than a public
issue. Expect an acknowledgement within 7 days.

## Scope and design notes

- Template files, design text and image metadata are treated as **data**. Nothing read from a template is executed
  or interpolated into a shell command.
- Paths inside a template are resolved with a traversal guard (`common.safe_path`); asset files are content-hashed
  and verified before rendering.
- Rendering runs a local headless Chromium on local files only; no network access is required.
- The engine never uploads references or templates anywhere.

Reports about prompt-injection through design text (for example a poster that says "ignore previous
instructions") are in scope: the skill's rules require such text to be treated as content.
