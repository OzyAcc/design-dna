# Portable test fonts

The acceptance suite's **portable** font set (`tests/fixtures/fontset.py`). These files let the suite run on Linux
and macOS without the Windows system fonts the 1.0.0 / 2.0.0 runs used, and every machine gets byte-identical
files, so font hashes, pins and bundle manifests agree across machines.

They are test fixtures. The engine never loads them unless a test (or you) supplies them as font files.

| File | Face | Version | Role in the suite | sha256 | Licence |
|---|---|---|---|---|---|
| `LiberationSans-Bold.ttf` | Liberation Sans Bold | 2.1.5 | sans: label + CTA of the layered reference (Arial's role) | `3973aa5054fb467dd5627245d3dc82e37bf16fe075756156a570455871351582` | SIL OFL 1.1 ([licenses/OFL-Liberation.txt](licenses/OFL-Liberation.txt)) |
| `DejaVuSerif-Bold.ttf` | DejaVu Serif Bold | 2.37 | serif: headline of the layered reference (Georgia's role); has no Arabic glyphs | `847b33e13925f19ff87e4d934d6b3cf7cac35ce16424f6f670e40c2f377cf2df` | Bitstream Vera licence, DejaVu changes public domain ([licenses/LICENSE-DejaVu.txt](licenses/LICENSE-DejaVu.txt)) |
| `DejaVuSans-Bold.ttf` | DejaVu Sans Bold | 2.37 | sans candidate (Verdana's role) | `5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895` | Bitstream Vera licence ([licenses/LICENSE-DejaVu.txt](licenses/LICENSE-DejaVu.txt)) |
| `Carlito-Bold.ttf` | Carlito Bold | 1.104 | sans candidate | `bb5d20f79b82599ec72983597437373a80f2d2085fa91fc144fd74e876a594db` | SIL OFL 1.1 ([licenses/OFL-Carlito.txt](licenses/OFL-Carlito.txt)) |
| `LiberationSerif-Bold.ttf` | Liberation Serif Bold | 2.1.5 | serif candidate | `9e66c25e20868756bf12eb24a520a4552727c9cd108f577f7ae33e3c0110e39c` | SIL OFL 1.1 ([licenses/OFL-Liberation.txt](licenses/OFL-Liberation.txt)) |
| `Caladea-Bold.ttf` | Caladea Bold | 1.001 | serif candidate | `ae3cb2dcbc925809dd29d2a44e9802211cab66be541bacbfc9c08c74b27c3742` | SIL OFL 1.1 ([licenses/OFL-Caladea.txt](licenses/OFL-Caladea.txt)) |
| `Amiri-Bold.ttf` | Amiri Bold | 1.002 | Arabic + Latin adaptation font (Arial's Arabic role): T17's long Arabic headline (920 px box) fits at the declared 56 px minimum and overflows at 84 px, as with Arial; DejaVu Sans's Arabic is too wide (1244 px at 56 px) | `cfccb794268e7d573d857e6d6a67f89cf8a053e8ffd85dfa0c8ec1bb36fc4827` | SIL OFL 1.1 ([licenses/OFL-Amiri.txt](licenses/OFL-Amiri.txt)) |
| `OpenSans-wdth-wght.ttf` | Open Sans (variable: `wght` 300–800, `wdth` 75–100) | 3.003 | T02's caption face, never a candidate (Bahnschrift's role); T27's `wdth` axis | `36643644f318a812aab2d2ed3bb98f8cf0872527f835fe9398d95fe6b9adb878` | SIL OFL 1.1 ([licenses/OFL-OpenSans.txt](licenses/OFL-OpenSans.txt)) |

Sources: Liberation, DejaVu, Carlito and Caladea are the unmodified files from the Debian/Ubuntu packages
`fonts-liberation` 2.1.5, `fonts-dejavu-core` 2.37, `fonts-crosextra-carlito` 20230309 and `fonts-crosextra-caladea`.
Open Sans is `ofl/opensans/OpenSans[wdth,wght].ttf` from [google/fonts](https://github.com/google/fonts), renamed
without brackets; Amiri is `ofl/amiri/Amiri-Bold.ttf` from the same repository. No file is modified. The OFL allows bundling the fonts with software; reserved font names are
untouched because nothing is a derivative.

## Choosing the set

`DESIGN_DNA_FONTSET=portable` forces these files on any platform, including Windows.
`DESIGN_DNA_FONTSET=windows` forces the Windows system fonts. Without the variable, Windows machines that have Arial
and Georgia use the `windows` set (the verified 1.0.0 / 2.0.0 configuration), and every other machine uses
`portable`. The acceptance report records which set ran and the faces behind each role.
