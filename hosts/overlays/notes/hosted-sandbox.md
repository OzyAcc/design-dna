## Running in a hosted sandbox (this package: ChatGPT Skills or Claude apps)

This copy of the skill was packaged for a vendor-hosted code sandbox. Such a sandbox can lack the Python packages
or the Chromium browser the engine needs, may have no network to install them, and is discarded after the chat.

1. Run `python scripts/capabilities.py` first and tell the user what it reports. If a package is missing and
   `pip install -r requirements.txt` fails, say which features are unavailable instead of improvising them:
   - no Pillow: nothing below works; switch to method guidance only and label every value as an estimate;
   - no numpy, scikit-image or scipy: intake works, measurement does not;
   - renderer `unavailable`: intake, measurement, colour sampling, validation and bundles work; font fitting,
     reconstruction, verification, verified edits and SVG export do not.
2. Set `DESIGN_DNA_HOME` to a folder inside the sandbox's working directory, and treat it as temporary.
3. Persist by exporting: after a scan, a reconstruct and each saved variant, run
   `dna.py 'export-template "<Name>" to <output folder>'` and give the user the `.dnab` file to download.
   At the start of a later chat, ask for that file and import it (`dna.py 'import-template <file>'`) before any edit.
4. Never claim a render, a pixel comparison or a verified edit unless the commands that produce them ran here.
