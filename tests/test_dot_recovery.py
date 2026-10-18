"""Known geometry tests independent of page names or Sinhala words."""
import unittest
from copy import deepcopy
from services.dot_recovery import recover_back_dots
from services.grouping import GridConfig,group_dots_detailed
from test_grouping import detections,text_lines


class RecoveryTests(unittest.TestCase):
    def test_invalid_candidate_confidence_is_not_recovered(self):
        _, rows = self.page()
        next(r for r in rows if r[0] == 1)[5] = 2.
        result = group_dots_detailed(rows, 1000, 1000, config=GridConfig(recover_back_dots=True))
        self.assertEqual(result['recovered_dots'], [])

    def test_competing_slots_do_not_claim_the_same_candidate(self):
        _, rows = self.page()
        grouped = group_dots_detailed(rows, 1000, 1000)
        target = next(c for c in grouped['cells'] if c['line'] == 0 and c['column'] == 3)
        duplicate = deepcopy(target)
        duplicate['token_index'] = len(grouped['codes'])
        grouped['codes'].append(duplicate['code'])
        grouped['cells'].append(duplicate)
        for reverse in (False, True):
            candidate = deepcopy(grouped)
            if reverse:
                candidate['cells'].reverse()
            result = recover_back_dots(candidate, rows, 1000, 1000)
            self.assertEqual(result['recovered_dots'], [])

    def test_duplicate_detection_records_do_not_supply_eight_anchors(self):
        _, rows = self.page()
        grouped = group_dots_detailed(rows, 1000, 1000)
        target = deepcopy(next(c for c in grouped['cells'] if c['line'] == 0 and c['column'] == 3))
        target['detections'] *= 8
        target['residuals'] *= 8
        grouped['cells'] = [target]
        result = recover_back_dots(grouped, rows, 1000, 1000)
        self.assertEqual(result['recovered_dots'], [])

    def page(self):
        expected=[['111111','111111','000000','110010','101100']]*3
        rows=detections(expected)
        for dot in rows:
            if abs(dot[1]-.22)<1e-8 and abs(dot[2]-.1)<1e-8:
                dot[0]=1
        return expected,rows

    def test_recovers_misclassified_dot_and_records_evidence(self):
        expected,rows=self.page()
        result=group_dots_detailed(rows,1000,1000,config=GridConfig(recover_back_dots=True))
        self.assertEqual(text_lines(result),expected)
        self.assertEqual(len(result['recovered_dots']),1)
        record=result['recovered_dots'][0]
        self.assertEqual(rows[record['detection']][0],1)
        self.assertTrue(result['requires_review'])
        self.assertNotEqual(result['raw_codes'],result['codes'])

    def test_recovery_is_opt_in(self):
        expected,rows=self.page()
        result=group_dots_detailed(rows,1000,1000)
        self.assertNotEqual(text_lines(result),expected)
        self.assertNotIn('recovered_dots',result)

    def test_blank_cells_and_offset_back_dots_are_not_filled(self):
        expected,rows=self.page()
        rows.extend([[1,.18,.10,.01,.01,.99], # Exact site in a blank cell.
                     [1,.235+.0075,.10+.0075,.01,.01,.99]]) # Back lattice, half a dot step away.
        result=group_dots_detailed(rows,1000,1000,config=GridConfig(recover_back_dots=True))
        self.assertEqual(text_lines(result),expected)
        self.assertEqual(len(result['recovered_dots']),1)

    def test_ambiguous_duplicates_and_same_class_setting_are_rejected(self):
        _,rows=self.page()
        rows.append(next(r.copy() for r in rows if r[0]==1))
        result=group_dots_detailed(rows,1000,1000,config=GridConfig(recover_back_dots=True))
        self.assertEqual(result['recovered_dots'],[])
        with self.assertRaises(ValueError):
            group_dots_detailed(rows,1000,1000,config=GridConfig(recover_back_dots=True,back_class_id=2))
