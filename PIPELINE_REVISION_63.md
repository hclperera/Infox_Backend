# Dot mapping and translation — 18 October 2026

This update builds on the existing local revision 6.2 changes. It does not
establish an overall recognition-accuracy increase on real pages.

## Mapping dots to cells

`refine_lines: true` now also refines regular grids, including calibrated
grids, before their quality check. Previously line refinement was available
only inside the curved-page fitter. This helps pages whose global spacing is
known but whose individual text lines bend slightly.

The candidate must reduce residual loss on both fitting and held-out dots,
preserve accepted-dot coverage, and meet the configured minimum on both the
whole page and held-out dots. Validation dots are distributed within each
line to avoid periodic sampling leaving entire lines without validation.
The existing distortion and reassignment guards still apply. Dot positions,
cell bits, residuals and overlay sites use the selected line models together.

Enable this experimentally in the JSON file referenced by
`BRAILLE_GRID_CONFIG` (or the grouping CLI's `--config`):

```json
{"refine_lines": true}
```

It remains opt-in. No acceptance threshold is lowered, and no words are used
to select geometry. Regular-fit diagnostics retain pixel units and expose
the selected models under `grid.line_refinement`. Calibration still needs
enough correct initial assignments; this cannot repair an arbitrary origin.

## Translation

- Accepts Unicode six-dot Braille as well as six-bit strings, with the same
  dots-1-through-6 bit order. Newline tokens preserve line boundaries.
- Malformed non-string tokens after prefixes produce replacement characters
  and indexed warnings instead of crashing look-ahead dictionary lookups.
  Eight-dot Unicode cells remain unsupported and are flagged.
- Optional `numeric_punctuation: true` keeps numeric mode through a comma or
  period between digits. Whitespace, other symbols and indexed overrides
  terminate that context. Existing decoding is the default.

The numeric option uses the comma/period continuation convention described in
[BANA's ABCs of UEB](https://www.brailleauthority.org/ueb/abcs/abcs-ueb.html).
This is a limited option, not complete UEB or mathematical Braille support;
the supplied Sinhala pages do not establish their numeric convention.

For the backend, point `BRAILLE_TRANSLATION_CONFIG` to a JSON file:

```json
{"numeric_punctuation": true, "roman_list_markers": true}
```

The same keywords can be passed to `translate_detailed`. With this option,
number-sign, 1, comma, 2, period, 3 becomes `1,2.3`; previously the cells after
the comma were decoded as Sinhala letters. Sinhala letter mappings are
unchanged.

## Verification

All 45 unit tests pass, including five added regressions. The calibrated
bent-line fixture fails the unrefined quality check; refinement reconstructs
all 80 independently specified cells and locates their sites within 0.1
pixels. Tests also cover incorrect calibration, spaces, Unicode bit order,
malformed look-ahead tokens, numeric boundaries and overrides.

Default translation reproduces all six saved T1–T6 review texts exactly.
Saved detection replay results are recorded locally in
`diagnostics/revision63/comparison.json`. These are regression comparisons,
not independent reference transcriptions. No model inference, retraining or
deployment was performed. Real-page accuracy still needs independently
verified cells/text; the existing evaluation script can measure that.
