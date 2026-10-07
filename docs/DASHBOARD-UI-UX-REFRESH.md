# Dashboard UI/UX refresh

Branch: `codex/dashboard-ui-ux-2026-10-07`  
Started from the merged dashboard on main, `65149025db661eee5a69f5b42cf1ce39e6244d39`; integrated the later documentation-only main update `724a02069ee7907d4f72198beb2ce242c73377ff` before delivery.

This update makes the existing template-first application easier to browse, understand and operate. The interface takes inspiration from [shadcn/ui](https://ui.shadcn.com/) for composable controls and application hierarchy, and [React Bits](https://reactbits.dev/) for restrained interaction and motion. The implementation is project-owned React/CSS; it does not vendor either project's component source or add an animation/component dependency.

## Resulting experience

| Area | What changes | Where |
|---|---|---|
| Workspace | Grouped navigation, collapsible desktop sidebar, sticky breadcrumbs and global actions | `dashboard/web/src/App.tsx` |
| Quick search | Ctrl/Cmd K opens navigation and real template-name search; arrow keys and Enter navigate; Escape closes | `components/CommandMenu.tsx` |
| Theme | Persistent light/dark mode using the same semantic colour tokens | `App.tsx`, `styles.css` |
| Library | Bigger previews, clear readiness labels, original/copy metadata, grid/list views, saved view preference | `pages/Library.tsx` |
| Find templates | Search, collection tabs, expanded filters including medium, sorting, clear filters and actionable empty/error states | `pages/Library.tsx` |
| Batch selection | Persistent selected-template dock opens the existing composer; output counts use actual selected products | `Library.tsx`, `components/Composer.tsx` |
| Inspiration intake | Upload/drop area, clipboard guidance and a separate URL field; unique input IDs | `components/AssetIntake.tsx`, `pages/NewTemplate.tsx` |
| Product input | Native modal drawer with inert background, focus containment, Escape and focus restoration; save-in-progress feedback | `components/Products.tsx`, `components/ui.tsx` |
| Template page | Clear explanation of a protected original or editable copy, improved inspector surfaces | `pages/TemplateDetail.tsx`, `styles.css` |
| Content review | Actual proposed/included/blocked counts; an upfront notice that creative reference mode omits text | `pages/Generate.tsx` |
| Results and settings | Consistent page hierarchy, clearer empty state, scrollable result table and provider actions | `pages/Runs.tsx`, `pages/Settings.tsx` |
| Motion | Short page/dialog entrance, mild card preview scale, subtle pointer spotlight and loading skeletons | `components/ui.tsx`, `styles.css` |

The library stays the entry point: select templates, add products, review each output, then generate. There is no analytics homepage or invented usage data. Previews, collections, readiness, versions, providers and batch counts continue to come from the existing API. Filter requests are sequenced so a slower earlier response cannot replace newer search results.

## Design rules

- Keep ivory `#F6F2EA`, near-black `#16130F` and crimson `#C8102E` as the default identity. Use refined serif page headings, quiet sans-serif controls and small monospace labels.
- Give reference artwork the largest surface. Keep status visible and distinguish Draft, Partial baseline, Editable close and Exact pixels using the engine's existing values.
- Use native buttons, labelled inputs, visible focus rings and native modal dialogs. Main navigation stays reachable without a pointer. Quick search also works through ordinary Tab navigation.
- Respect `prefers-reduced-motion`: remove decorative animation, hover scaling, spotlight effects and smooth scrolling. Motion never changes template rendering or engine measurements.
- Keep UI display themes separate from design-model colours. Dark mode changes application chrome, not the source image or output model.
- Keep mobile navigation and product editing modal; Escape and closing restore the triggering control. Collection tabs and result tables scroll inside their containers.
- A protected original must invite a copy before editing. Do not hide unknown fonts, partial reconstruction or failed checks behind a cosmetic success label.

## Implementation notes

`components/ui.tsx` owns icons, PageHeader, EmptyState, skeletons, Dialog and Spotlight. The icon paths and effects are original project code. `styles.css` retains the existing engine-facing viewers and scan canvas styles, followed by the refreshed application rules; semantic tokens define both themes. The four larger new/refactored React files are formatted for review.

No server schema, provider adapter, engine script, rendering pin, bundle contract, billing or account system changes are included. No new runtime dependencies are required. Existing local startup and Docker instructions still apply.

### Existing generation limitations

This is a UI/UX change. The earlier audit's pending-save/submission, uncertain submission-retry and post-response paid-request recovery issues still require separate functional fixes before unattended paid usage. The new creative-mode notice makes its current imagery-only behavior visible before submission; it does not implement text composition for creative raster outputs. Live provider generation and SaaS account/billing/BYOK readiness are not established by this branch.

## Verification

The TypeScript/Vite production build and Python static checks passed during implementation. Final browser/integration results and screenshot evidence are recorded below before branch delivery.

The browser suite includes the original all-page checks at 390 and 1280 px and keyboard navigation, plus new tests for persistent library views/themes, copy filtering and selection, command navigation/Escape/focus restoration, and product-drawer focus containment on a narrow screen. AI providers in these tests are explicitly labelled mocks; the API, worker, SQLite records and design engine are real.

Optional screenshots are produced with `DNA_UI_SCREENSHOTS=<directory>` when running `dashboard/tests/test_ui.py`; the checked-in screenshots show isolated test fixtures, not customer designs or live AI generation. Reproduce the suite with:

```bash
cd dashboard/web
npm ci --no-audit --no-fund
npm run build
cd ../tests
DNA_REQUIRE_UI_TEST=1 python -m unittest -v test_intake test_templates test_batches test_execution test_ui
```

Use the project's normal Python dependencies and installed Playwright Chromium. The local audit workspace used packaged Chromium 153.0.8010.0 because the standard browser archive download was unavailable there; no renderer-selection code was modified for that environment. CI uses the existing Playwright installation workflow.

### Final local results

| Check | Result |
|---|---|
| Production build | Pass: TypeScript + Vite; JS 126.85 kB gzip, CSS 10.17 kB gzip |
| API/engine integration | All 36 non-browser tests passed in the full 41-test run |
| Final browser regression | All 5 tests passed in 64.447 seconds after correcting product-drawer Tab wrapping |
| Layout/accessibility-name coverage | Every existing application page at 390 and 1280 px; no horizontal document overflow, unnamed visible controls or browser script errors; library list view also checked at 768 px |
| Static checks | Python pyflakes and `git diff --check` passed |
| Live AI providers | Not exercised; integration uses labelled test-only mock providers |

The initial full run passed 40 of 41 tests and found the new drawer focus edge case. The final source explicitly wraps Tab/Shift Tab inside dialogs, and all browser tests were rerun against the rebuilt frontend. API/engine code was unchanged by that correction. Screenshots below were regenerated from that final browser run.

### Screenshots

These are real browser captures of the implemented interface with isolated test fixtures. The template poster is a synthetic engine fixture and its Partial rebuild label is real; it is not a customer product or a live generated result.

- [Library, light, desktop](images/dashboard-ui-refresh/library-1280.png)
- [Library, dark list view, desktop](images/dashboard-ui-refresh/library-dark-1280.png)
- [Library, mobile](images/dashboard-ui-refresh/library-390.png)
- [Inspiration intake, desktop](images/dashboard-ui-refresh/intake-1280.png)
- [Inspiration intake, mobile](images/dashboard-ui-refresh/intake-390.png)
