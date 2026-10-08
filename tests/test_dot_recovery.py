"""Known geometry tests independent of page names or Sinhala words."""
import unittest
from services.grouping import GridConfig,group_dots_detailed
from test_grouping import detections,text_lines


class RecoveryTests(unittest.TestCase):
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
