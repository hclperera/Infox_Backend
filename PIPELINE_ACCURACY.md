# Pipeline improvements — 15 October 2026

Revision 6.2 selectively incorporates the supplied grouping revision and adds
recovery safeguards and an independent evaluation entry point. It does not
change model weights, detector thresholds, Sinhala mappings or the default
90% geometric acceptance threshold.

## Changes enabled by default

- Each occupied dot slot contributes exactly one supporting detection. The
  lowest normalized geometric residual wins, followed by highest confidence
  and then detection index for ties. Other detections are recorded as slot
  collisions. This preserves the occupied bit while preventing duplicate
  evidence from inflating recovery support.
- Grouping reports `slot_collision_count`, `unique_slot_count`,
  `retained_detection_count`, and `unique_slot_fraction` alongside the existing
  `accepted_fraction`. The latter remains the fraction of retained detections
  on the grid before slot deduplication. `unique_slot_fraction` divides unique
  occupied slots by retained detections. Neither is character accuracy, and
  these statistics describe the fit before optional back-dot recovery.
- Coordinate clustering uses a running sum. Overlay inversion is batched per
  line, accepts empty inputs and uses a pseudoinverse for its initial estimate.
  Final convergence and grid-distortion checks remain in force.

## Optional features

Set `preserve_leading_spaces` to true in your existing `BRAILLE_GRID_CONFIG`
JSON file, or in the configuration passed to `scripts/group_dots.py`:

```json
{"preserve_leading_spaces": true}
```

This aligns lines to the leftmost occupied column across the page. It cannot
infer a completely blank left margin or trailing whitespace. The default is
false, preserving previous output formatting.

Back-dot recovery remains opt-in (`recover_back_dots: true`) and requires
review. Its additional safeguards now:

- reject invalid candidate confidence scores;
- count distinct detection IDs when checking nearby anchor support;
- require exactly one candidate per eligible slot and exactly one eligible
  slot per candidate before applying any recovery;
- ignore a singular coarse reference frame instead of crashing recovery;
- resolve the back class from detector metadata in the backend and CLI.
  Unknown or ambiguous class names require an explicit `back_class_id`.

Bare YOLO labels without class metadata retain the historical defaults
(`front_class_id: 2`, `back_class_id: 1`). For a two-class model, provide its
actual IDs or use the backend detection JSON with `class_names`. Calling
`group_dots_detailed` directly still uses the IDs in its supplied `GridConfig`.

## Measure recognition errors

Create a manifest with independently verified reference codes and, optionally,
correct Sinhala text. Do not copy algorithm output into the reference fields.
This illustrative entry represents the single cell for ක followed by a newline:

```json
{
  "pages": [
    {
      "id": "verified-page-1",
      "detections": "verified-page-1/detections.json",
      "expected_codes": ["101000", "\n"],
      "expected_text": "ක\n"
    }
  ]
}
```

Detection JSON must contain `yolo_outputs`, `img_width`, and `img_height`;
include `front_class_id` and `class_names` when available. Detection paths are
relative to the manifest. A sparse example like the illustrative one above
requires measured calibration to establish the cell origin.

```powershell
python scripts/evaluate_pipeline.py path/to/manifest.json
python scripts/evaluate_pipeline.py path/to/manifest.json --config path/to/grid.json
```

The JSON report includes:

- cell edit error rate (insertions, deletions and substitutions; newlines excluded);
- layout token edit error rate (cells and newlines included);
- Sinhala character error rate using NFC-normalized Unicode code points,
  preserving spaces and newlines (not grapheme-cluster error rate);
- exact-code page fraction, with failed pages counted as non-exact;
- explicit failed-page counts and error messages.

Edit error rates cover completed pages only and can exceed 100% when there
are many insertions. Always compare failures alongside the error rates. No
character rate is reported when text references are absent or have zero total
length. This tool evaluates grouping and translation from saved detections;
it does not run inference or measure dot-detection precision/recall.

Use a development set to choose configurations and a separate, untouched test
set to report final results. Include curved pages, sparse text, double-sided
Braille and phone photographs. Changing detector settings requires generating
new detection JSON for the same evaluation pages.

## Verification performed

- All 31 regression tests pass (20 existing, 11 added).
- Replayed all six saved V8-v2 pages with the previous revision-6 review
  configurations. All six produced identical Braille codes and recovery counts.
- Under default quality settings, T1, T2, T4 and T5 complete; T3 and T6 still
  fail the geometric reliability check. No thresholds were lowered to make
  those pages pass.
- The local replay report is `diagnostics/revision62/comparison.json`.

This verifies the targeted safeguards and preservation of the saved outputs;
it does not demonstrate an end-to-end accuracy increase. No new model
inference, server deployment or database migration was performed.

## 16 October: uploaded scans 160, 162 and 167

The uploaded scan-167 grouping result identifies server revision
`2026-10-08-r6`. The local revision-6.2 changes were not used for that saved
result. Replaying the supplied detections reproduces the reported failures.

- Scan 160: 1,034 front detections; default fitting accepts 91.3% overall and
  89.9% of held-out dots. Optional line refinement does not resolve the
  failure. The 90% threshold has not been lowered. This scan remains unresolved.
- Scan 162: page detection failed. The image contains desk/laptop background
  and only part of the Braille page. The old pipeline nevertheless ran dot
  detection on the whole image (281 front detections), then failed to find a
  reliable grid. When page cropping is enabled, the updated vision stage now
  stops with a retake instruction. It saves `page_detection_failed.png` when
  a debug directory is available. `PAGE_ALLOW_FULL_IMAGE=1` explicitly restores
  the previous fallback; `PAGE_CROP=0` continues to bypass page detection.
  This prevents background processing; it does not reconstruct a missing page.
- Scan 167: 1,274 front detections, 221 near-coincident other-class conflicts,
  and 63 excluded off-grid dots. These counts are diagnostic evidence, not
  measured false-positive counts. Recovery/refinement does not establish
  correct text.

All five replacement characters in scan 167 came from the same unsupported
dots-56 prefix before list labels i, ii, iii, iv and v. Translation now supports
explicitly marked, canonical lowercase Roman numerals followed by a period
at the start of a line (allowing indentation). It requires a space, newline
or end-of-input after the period and respects indexed overrides. Mid-sentence,
unmarked, incomplete and invalid sequences retain existing behavior.

The convention is documented in [BANA's ABCs of UEB, section 6.5](https://www.brailleauthority.org/ueb/abcs/abcs-ueb.html),
which compares EBAE and UEB Roman numerals. Its use in these Sinhala-page list
labels is inferred from the explicit prefix and i-through-v sequence; each
interpretation remains recorded as a warning. This is not general English
Braille support. Call `translate_detailed(..., roman_list_markers=False)` to
disable it for a different transcription convention.

On the exact saved scan-167 codes, this changes five list labels and reduces
replacement characters from five to zero. Other text remains unchanged and
contains recognition errors. Local outputs are in
`output/scans_20261016/167_before.txt` and `167_after.txt`. All six previous
T1–T6 review texts remain unchanged by this translation update.

All 40 regression tests pass. Additional files for this follow-up are
`services/page_validation.py`, `tests/test_page_validation.py` and
`tests/test_translation.py`; modified files are `services/segmentation.py`,
`services/translation.py` and this guide. New detector inference and live-server
deployment have not been performed. The missing-page policy is unit-tested;
model integration has not been exercised in this local runtime.
