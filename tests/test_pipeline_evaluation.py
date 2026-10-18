import json
from pathlib import Path
import tempfile
import unittest
from scripts.evaluate_pipeline import compare_output, edit_distance, evaluate
from test_grouping import detections


class PipelineEvaluationTests(unittest.TestCase):
    def test_insertions_deletions_and_layout_errors(self):
        self.assertEqual(edit_distance('abc', 'axbc'), 1)
        self.assertEqual(edit_distance('abc', 'ac'), 1)
        result = compare_output(['100000', '\n', '101000', '\n'],
                                ['100000', '101000', '\n'], 'a b', 'ab')
        self.assertEqual(result['cell_edits'], 0)
        self.assertEqual(result['layout_token_edits'], 1)
        self.assertEqual(result['character_edits'], 1)
        self.assertFalse(result['exact_codes'])

    def test_failed_pages_are_visible_and_count_against_exact_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'dots.json').write_text(json.dumps({
                'yolo_outputs': detections([['111111'] * 3]),
                'img_width': 1000, 'img_height': 1000, 'front_class_id': 2}), encoding='utf-8')
            expected = ['111111'] * 3 + ['\n']
            (root / 'manifest.json').write_text(json.dumps({'pages': [
                {'detections': 'dots.json', 'expected_codes': expected},
                {'detections': 'missing.json', 'expected_codes': expected}]}), encoding='utf-8')
            report = evaluate(root / 'manifest.json')
            self.assertEqual(report['summary']['failed_pages'], 1)
            self.assertEqual(report['summary']['exact_codes_page_fraction'], .5)
            self.assertEqual(report['summary']['cell_error_rate_completed_pages'], 0.)
            self.assertIsNone(report['summary']['character_error_rate_completed_pages'])
