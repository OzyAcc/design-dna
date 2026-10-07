# ChatGPT: moved

This page used to be an untested adaptation guide. It is replaced by:

- **[docs/hosts/chatgpt.md](hosts/chatgpt.md)**: the installable ChatGPT Skills package (Business, Enterprise,
  Healthcare and Edu workspaces), Codex for every plan, and the labelled instruction kit for Free, Plus and Pro.
- **[docs/hosts/COMPATIBILITY.md](hosts/COMPATIBILITY.md)**: every AI tool, what runs there, documentation sources
  and test status.

One point from the old page still stands. Inside a hosted sandbox (ChatGPT Skills, Claude apps), templates
persist only as `.dnab` bundles that the user downloads and uploads again. A storage adapter that writes bundles
to a host's own file store through an API (`bundle.StorageBackend`) is still not included or tested: acceptance
entry 23 stays **unverified**.
