# Compatibility registry

Generated from [`hosts/registry/`](../../hosts/registry/) by `python install.py docs`. Documentation checked 2026-10-07. AI-host results only: operating-system test results are in [BUILD-REPORT](../BUILD-REPORT.md) and [CAPABILITIES](../../CAPABILITIES.md); installer results per operating system are in [EVIDENCE](EVIDENCE.md).

## Hosts

| Host | Surfaces | Install method | Skill folder (user / project) | Capability |
|---|---|---|---|---|
| [ChatGPT](chatgpt.md) | 2 | upload a zip, instruction kit (fallback) | — | Hosted code sandbox, Instructions only (fallback) |
| [OpenAI Codex](codex.md) | 2 | skill folder, plugin / extension | `~/.agents/skills` / `.agents/skills` | Local agent with a shell |
| [Claude Code](claude-code.md) | 2 | skill folder, plugin / extension | `~/.claude/skills` / `.claude/skills` | Local agent with a shell |
| [Claude apps (web, desktop, mobile)](claude-apps.md) | 1 | upload a zip | — | Hosted code sandbox |
| [Cursor](cursor.md) | 1 | skill folder | `~/.cursor/skills` / `.cursor/skills` | Local agent with a shell |
| [GitHub Copilot](copilot.md) | 3 | skill folder, plugin / extension | `~/.copilot/skills` / `.github/skills` | Local agent with a shell, Hosted code sandbox |
| [Gemini CLI](gemini-cli.md) | 2 | skill folder, plugin / extension | `~/.gemini/skills` / `.gemini/skills` | Local agent with a shell |
| [Windsurf](windsurf.md) | 1 | skill folder | `~/.codeium/windsurf/skills` / `.devin/skills` | Local agent with a shell |
| [Cline](cline.md) | 1 | skill folder | `~/.cline/skills` / `.cline/skills` | Local agent with a shell |
| [Roo Code](roo-code.md) | 1 | skill folder | `~/.roo/skills` / `.roo/skills` | Local agent with a shell |
| [OpenCode](opencode.md) | 1 | skill folder | `~/.config/opencode/skills` / `.opencode/skills` | Local agent with a shell |
| [Kiro](kiro.md) | 1 | skill folder | `~/.kiro/skills` / `.kiro/skills` | Local agent with a shell |
| [Junie (JetBrains)](junie.md) | 1 | skill folder | `~/.junie/skills` / `.junie/skills` | Local agent with a shell |
| [Goose](goose.md) | 1 | skill folder | `~/.agents/skills` / `.agents/skills` | Local agent with a shell |
| [Other Agent Skills hosts (shared .agents folder)](agents.md) | 1 | skill folder | `~/.agents/skills` / `.agents/skills` | Local agent with a shell |
| [Any chat assistant without skills (instruction kit)](instructions.md) | 1 | instruction kit (fallback) | — | Instructions only (fallback) |

## Host test results

Stages: **install** (the package lands where the host looks), **discovery** (the host lists the skill), **invocation** (the host's model loads it), **scan** (it runs a scan), **persistence** (a template survives into a new session), **editing** (a controlled edit is verified). ✅ verified: observed working in the build environment; evidence linked. 🟡 partial: part of the stage was observed; the evidence says which part. ⚪ untested: no access to the host from the build environment; nothing is claimed. n/a: the stage does not exist on this surface.

| Host | install | discovery | invocation | scan | persistence | editing |
|---|---|---|---|---|---|---|
| ChatGPT | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| OpenAI Codex | ✅ verified | ✅ verified | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Claude Code | ✅ verified | ✅ verified | ✅ verified | ✅ verified | ✅ verified | ✅ verified |
| Claude apps (web, desktop, mobile) | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Cursor | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| GitHub Copilot | ✅ verified | ✅ verified | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Gemini CLI | ✅ verified | ✅ verified | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Windsurf | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Cline | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Roo Code | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| OpenCode | ✅ verified | ✅ verified | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Kiro | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Junie (JetBrains) | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Goose | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Other Agent Skills hosts (shared .agents folder) | ✅ verified | 🟡 partial | ⚪ untested | ⚪ untested | ⚪ untested | ⚪ untested |
| Any chat assistant without skills (instruction kit) | 🟡 partial | n/a | ⚪ untested | n/a | n/a | n/a |

## What works at each capability level

| Feature | Needs | Local agent with a shell | Hosted code sandbox | Instructions only (fallback) |
|---|---|---|---|---|
| Method guidance: scan categories, evidence statuses, honest claims | instructions only | yes | yes | yes |
| Intake: source hash, metadata, canonical sRGB copy, skeleton template | Python 3.10+ with Pillow | yes | expected; untested | no |
| Measurement: ink boxes, profiles, edges, radius, shadow, role colours | Python with numpy, Pillow, scikit-image, scipy | yes | expected if numpy, scikit-image and scipy are present; untested | no: visual estimates, labelled inferred |
| Validation, annotated scan, scan report, bundles | Python with jsonschema, Pillow, fontTools | yes | expected; untested | no |
| Font candidate ranking and render-fitted typography | Python packages, a Chromium that Playwright can launch, candidate font files | yes, with Chromium | only if the sandbox can launch Chromium; untested | no |
| Reconstruct, pixel and region verification, PNG + SVG export with round trip | Python packages and Chromium | yes, with Chromium | only if the sandbox can launch Chromium; untested | no |
| Controlled edits verified against the previous revision and the approved baseline | Python packages and Chromium | yes, with Chromium | only if the sandbox can launch Chromium; untested | no: described changes, not verified ones |
| Template persistence across sessions | a writable store that outlives the session (~/design-dna), or .dnab bundles the user keeps | yes: ~/design-dna plus bundles | no: download bundles and upload them again | no: keep the scene JSON and passport the assistant writes |

## Documentation sources

| Host | Source | How it was read | Facts used |
|---|---|---|---|
| ChatGPT | [Skills in ChatGPT](https://help.openai.com/en/articles/20001066-skills-in-chatgpt) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Business, Enterprise, Healthcare and Edu plans; Free, Plus and Pro are not in the rollout. Plugins in the sidebar, Skills tab. Create, then Upload from your computer. Enterprise and Edu admins enable Skills under Permissions & Roles. skill-creator is included by default. |
| ChatGPT | [Build skills](https://learn.chatgpt.com/docs/build-skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | A skill is a folder anchored by SKILL.md with name and description. ChatGPT and Codex read the name and description first and load SKILL.md when they use the skill. |
| ChatGPT | [Skills (API guide)](https://developers.openai.com/api/docs/guides/tools-skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Upload a zip that contains a single top-level folder (recommended). The API accepts zips up to 50 MB and up to 500 files per hosted skill version. |
| ChatGPT | [Package your plugin](https://developers.openai.com/codex/plugins/build) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Public plugins are published once to the universal plugin directory shared by ChatGPT and Codex; local and repository marketplaces serve authoring, testing and team distribution. |
| OpenAI Codex | [Agent Skills (Codex)](https://developers.openai.com/codex/skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Skill locations: $CWD/.agents/skills, parents up to $REPO_ROOT/.agents/skills, $HOME/.agents/skills, /etc/codex/skills, bundled system skills. Optional agents/openai.yaml sets interface fields and policy such as allow_implicit_invocation. |
| OpenAI Codex | [Package your plugin](https://developers.openai.com/codex/plugins/build) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | A plugin folder has .codex-plugin/plugin.json and skills/<name>/SKILL.md. Marketplaces live at $REPO_ROOT/.agents/plugins/marketplace.json or ~/.agents/plugins/marketplace.json; source.path is ./-prefixed and relative to the marketplace root. codex plugin marketplace add takes owner/repo, Git URLs or local paths. |
| OpenAI Codex | [openai/plugins (official examples)](https://github.com/openai/plugins) | read in the vendor's public documentation repository at the commit named (5fd93af) | .codex-plugin/plugin.json declares "skills": "./skills/" and an interface block; .agents/plugins/marketplace.json lists plugins with source {source: local, path} and a policy. |
| OpenAI Codex | [Use Agent Skills in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-skills) | read in the vendor's public documentation repository at the commit named (microsoft/vscode-docs@4fe6b03) | Codex discovers .agents/skills natively. |
| Claude Code | [Agent Skills (Claude Code)](https://code.claude.com/docs/en/skills) | observed by running the host in the build environment | Personal skills in ~/.claude/skills/<name>/SKILL.md, project skills in .claude/skills/<name>/SKILL.md; plugins bundle skills under skills/. |
| Claude apps (web, desktop, mobile) | [Use skills in Claude](https://support.claude.com/en/articles/12512180) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Free, Pro, Max, Team and Enterprise; requires code execution. Customize > Skills > Upload a skill takes a ZIP of the skill folder. Uploads are private to the account; Team and Enterprise owners can provision skills for the organization. |
| Cursor | [Agent Skills (Cursor)](https://cursor.com/docs/skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Loads .agents/skills, .cursor/skills, ~/.agents/skills and ~/.cursor/skills, and for compatibility .claude/skills, .codex/skills, ~/.claude/skills and ~/.codex/skills. Nested project folders are scoped. Only ~/.cursor/skills syncs to cloud agents. |
| GitHub Copilot | [About agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) | read in the vendor's public documentation repository at the commit named (github/docs@8794b3c) | Skills work with the cloud agent, code review, Copilot CLI, the Copilot app, and agent mode in VS Code and JetBrains IDEs. Project skills: .github/skills, .claude/skills, .agents/skills. Personal skills: ~/.copilot/skills, ~/.agents/skills. gh skill (public preview, gh 2.90+) installs skills from repositories. |
| GitHub Copilot | [About GitHub Copilot plugins / CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference) | read in the vendor's public documentation repository at the commit named (github/docs@8794b3c) | Agent Plugins 1.0: plugin.json at the plugin root with the agent-plugins.org $schema; skills only from skills/. Legacy plugins also read .claude-plugin/plugin.json; marketplaces are read from marketplace.json, .github/plugin/marketplace.json or .claude-plugin/marketplace.json. copilot plugin install accepts a local path. |
| GitHub Copilot | [Use Agent Skills in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-skills) | read in the vendor's public documentation repository at the commit named (microsoft/vscode-docs@4fe6b03) | Project skills: .github/skills, .claude/skills, .agents/skills. Personal skills: ~/.copilot/skills, ~/.claude/skills, ~/.agents/skills. chat.agentSkillsLocations is deprecated. |
| Gemini CLI | [Agent Skills (Gemini CLI)](https://geminicli.com/docs/cli/skills/) | read in the vendor's public documentation repository at the commit named (google-gemini/gemini-cli@ef59c53 docs/cli/skills.md) | Discovery tiers: built-in, extension, user (~/.gemini/skills or the ~/.agents/skills alias), workspace (.gemini/skills or .agents/skills). gemini skills list|install|uninstall; /skills list|reload. Activation asks for consent. |
| Gemini CLI | [Extension reference](https://geminicli.com/docs/extensions/reference/) | read in the vendor's public documentation repository at the commit named (google-gemini/gemini-cli@ef59c53 docs/extensions/reference.md) | An extension has gemini-extension.json at its root; skills go in skills/<name>/SKILL.md. gemini extensions install <GitHub URL or local path> [--consent]; gemini extensions link <path>. |
| Windsurf | [Cascade Skills](https://docs.windsurf.com/windsurf/cascade/skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | User skills in ~/.codeium/windsurf/skills/; workspace skills in .devin/skills/<name>/ (legacy .windsurf/skills/ still read). SKILL.md with name and description; progressive disclosure. |
| Cline | [Skills (Cline)](https://docs.cline.bot/customization/skills) | read in the vendor's public documentation repository at the commit named (cline/cline@e5dd38d docs/customization/skills.mdx) | Global ~/.cline/skills/ (C:\Users\USERNAME\.cline\skills\ on Windows); project .cline/skills/, .clinerules/skills/, .claude/skills/. name must match the folder; description up to 1024 characters; use_skill tool or /<skill> slash command. |
| Roo Code | [Skills (Roo Code)](https://docs.roocode.com/features/skills) | read in the vendor's public documentation repository at the commit named (RooCodeInc/Roo-Code-Docs@a676c41) | Global ~/.roo/skills/ and ~/.agents/skills/ (%USERPROFILE% on Windows); project .roo/skills/ and .agents/skills/. Project overrides global; .roo overrides .agents at the same level; mode-specific folders override generic ones. |
| OpenCode | [Agent Skills (OpenCode)](https://opencode.ai/docs/skills/) | read in the vendor's public documentation repository at the commit named (sst/opencode@ecc4916 packages/web/src/content/docs/skills.mdx) | Project .opencode/skills, .claude/skills and .agents/skills (walking up to the git worktree); global ~/.config/opencode/skills, ~/.claude/skills and ~/.agents/skills. Name rules match the Agent Skills spec; loaded through the native skill tool; permissions in opencode.json. |
| Kiro | [Skills (Kiro)](https://kiro.dev/docs/skills/) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Workspace .kiro/skills/ and global ~/.kiro/skills/; workspace wins on a name clash; the default agent loads both with no configuration. |
| Junie (JetBrains) | [Agent skills (Junie)](https://junie.jetbrains.com/docs/agent-skills.html) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Project <projectRoot>/.junie/skills/<name>/; user ~/.junie/skills/<name>/ (%USERPROFILE%\.junie\skills on Windows). Skills are invoked only when they match the task. |
| Goose | [Using skills (Goose)](https://goose-docs.ai/docs/guides/context-engineering/using-skills) | read from search-engine excerpts of the vendor's official page (the build environment's network policy blocked the page itself) | Global ~/.agents/skills/, project .agents/skills/, plugin skills under ~/.agents/plugins/<name>/; also reads .goose/skills, .claude/skills, ~/.claude/skills and ~/.config/goose/skills. /skills lists and loads skills. |
| Other Agent Skills hosts (shared .agents folder) | [Agent Skills specification and client list](https://agentskills.io/specification) | read in the vendor's public documentation repository at the commit named (agentskills/agentskills@69ef37e) | name: 1-64 lowercase letters, digits and single hyphens, matching the folder; description 1-1024 characters; optional license, compatibility (up to 500 characters), metadata, allowed-tools (experimental). The client list names 46 products. |
