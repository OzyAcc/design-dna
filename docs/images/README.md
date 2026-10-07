# Design DNA README images

These six generated images illustrate the workflow. They are conceptual artwork,
not engine screenshots, exact reconstruction proofs, measured heatmaps or test results.

| File | Purpose |
|---|---|
| `banner.png` | Design DNA hero and reusable design layers |
| `demo-edits.png` | Copy, accent-color and product-image replacements |
| `demo-scan.png` | Typography, palette, layout, image treatment, depth and message hierarchy |
| `demo-rebuild.png` | Flat reference, editable model and rebuild |
| `demo-arabic-reflow.png` | English, Arabic and portrait story examples |
| `demo-catch.png` | Wording and position differences |

The image set uses ivory paper, ink, crimson, editorial serif headlines and
monospace labels. The photorealistic handbags are fictional examples without a
named product brand. Arabic example: `صُنعت لكلّ يوم`.

All six were produced with the built-in image generation tool. The full prompts
are in [IMAGE-PROMPTS.md](IMAGE-PROMPTS.md). Subsequent images should follow the
banner's art direction and retain a visible illustration label.

The original v1.0.0 acceptance screenshots are retained byte-for-byte in
[evidence/v1.0.0/](evidence/v1.0.0/). `docs/tools/make_images.py` now defaults to
`docs/images/evidence/latest/`, so regenerating evidence does not overwrite these
README illustrations. The repository's acceptance suite and build report remain
the sources for measured claims.

## Dashboard screenshots

`dashboard/` holds real screenshots of the web app, not illustrations. `dashboard/tests/screenshots.py` builds them
from a fresh workspace: synthetic, unbranded fixtures (the test poster and simple product photos), no provider
keys, and the mock providers switched off. Each picture shows what the app actually displayed. The engine's reports
and the output files, not these pictures, are the evidence for rendering and preservation.
