r"""Evaluate saved detector JSON against independently verified codes/text.

Manifest: {"pages": [{"id": "page-1", "detections": "detections.json",
"expected_codes": ["101000", "\n"], "expected_text": "..."}]}.
Paths are relative to the manifest. Text is optional. No images or models run.
"""
import argparse
import json
from pathlib import Path
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grouping import group_dots_detailed
from services.pipeline_config import grid_config_for_vision
from services.translation import translate_detailed


def edit_distance(reference, prediction):
    previous = list(range(len(prediction) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(prediction, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j-1] + (expected != actual)))
        previous = current
    return previous[-1]


def compare_output(expected_codes, codes, expected_text=None, text=None):
    reference_cells = [c for c in expected_codes if c != '\n']
    predicted_cells = [c for c in codes if c != '\n']
    result = {
        'exact_codes': codes == expected_codes,
        'cell_edits': edit_distance(reference_cells, predicted_cells),
        'reference_cells': len(reference_cells),
        'layout_token_edits': edit_distance(expected_codes, codes),
        'reference_layout_tokens': len(expected_codes),
    }
    if expected_text is not None:
        reference = unicodedata.normalize('NFC', expected_text)
        actual = unicodedata.normalize('NFC', text)
        result.update(character_edits=edit_distance(reference, actual),
                      reference_characters=len(reference), exact_text=reference == actual)
    return result


def evaluate(manifest_path, settings=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    pages = manifest['pages']
    if not isinstance(pages, list) or not pages:
        raise ValueError('Manifest must contain a nonempty pages list')
    records = []
    for page in pages:
        expected = page['expected_codes']
        if (not isinstance(expected, list) or not expected
                or any(not isinstance(c, str) or (c != '\n' and
                       (len(c) != 6 or set(c) - {'0', '1'})) for c in expected)):
            raise ValueError('expected_codes must contain six-bit strings or newline tokens')
        if 'expected_text' in page and not isinstance(page['expected_text'], str):
            raise ValueError('expected_text must be a string')
        record = {'id': page.get('id', page['detections']), 'status': 'error'}
        try:
            path = manifest_path.parent / page['detections']
            vision = json.loads(path.read_text(encoding='utf-8-sig'))
            grouped = group_dots_detailed(vision['yolo_outputs'], vision['img_width'],
                                         vision['img_height'],
                                         config=grid_config_for_vision(vision, settings))
            if not grouped['codes']:
                raise ValueError('No usable front dots')
            translated = translate_detailed(grouped['codes'])
            record.update(status='complete', **compare_output(
                expected, grouped['codes'], page.get('expected_text'), translated['text']))
            record['geometric_coverage'] = grouped['grid']['accepted_fraction']
            record['grouping_warnings'] = grouped['warnings']
            record['translation_warnings'] = translated['warnings']
        except (ValueError, TypeError, KeyError, OSError) as error:
            record['error'] = str(error)
        records.append(record)
    complete = [r for r in records if r['status'] == 'complete']
    summary = {'pages': len(records), 'completed_pages': len(complete),
               'failed_pages': len(records) - len(complete),
               'exact_codes_page_fraction': sum(r['exact_codes'] for r in complete)/len(records)}
    for metric, numerator, denominator in (
        ('cell_error_rate', 'cell_edits', 'reference_cells'),
        ('layout_token_error_rate', 'layout_token_edits', 'reference_layout_tokens'),
        ('character_error_rate', 'character_edits', 'reference_characters'),
    ):
        count = sum(r.get(denominator, 0) for r in complete)
        summary[metric + '_completed_pages'] = (
            sum(r.get(numerator, 0) for r in complete)/count if count else None)
    return {'summary': summary, 'pages': records,
            'notes': ['Error rates cover completed pages only; inspect failed_pages alongside them.',
                      'Cell errors exclude newlines; layout token errors include them.',
                      'Character errors use NFC Unicode code points, preserving spaces/newlines.',
                      'Geometric coverage is not recognition accuracy.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--config', type=Path, help='GridConfig JSON applied to all pages')
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    report = evaluate(args.manifest, settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report['summary']['failed_pages'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
