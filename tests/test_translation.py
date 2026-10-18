import unittest
from services.translation import translate_detailed


class RomanListTests(unittest.TestCase):
    def test_unicode_braille_preserves_bit_order_and_layout(self):
        codes = ['101000', '010100', '000000', '001111', '100000', '110000', '\n']
        unicode_codes = [chr(0x2800 + sum((c == '1') << bit for bit, c in enumerate(code)))
                         if code != '\n' else code for code in codes]
        self.assertEqual(translate_detailed(unicode_codes)['text'], 'කි 12\n')

    def test_malformed_lookahead_does_not_crash_or_consume_valid_cells(self):
        for prefix in ('001111', '000100', '011000', '000011', '000010'):
            for invalid in ([], {}, None, 17, '\u2840'):
                with self.subTest(prefix=prefix, invalid=invalid):
                    result = translate_detailed([prefix, invalid, '101000'])
                    self.assertTrue(result['text'].endswith('�ක'))
                    self.assertTrue(any(w['index'] == 1 for w in result['warnings']))

    def test_numeric_punctuation_is_explicit_and_does_not_leak(self):
        codes = ['001111', '100000', '010000', '110000', '010011', '100100',
                 '000000', '110000']
        self.assertEqual(translate_detailed(codes, numeric_punctuation=True)['text'], '1,2.3 බ')
        self.assertEqual(translate_detailed(codes)['text'], '1,බ.ච බ')
        result = translate_detailed(codes, numeric_punctuation=True, overrides={3: 'X'})
        self.assertEqual(result['text'], '1,X.ච බ')

    def test_marked_roman_list_labels(self):
        mapping = {'i': '010100', 'v': '111001', 'x': '101101', 'l': '111000',
                   'c': '100100', 'd': '100110', 'm': '101100'}
        for label in ('i', 'ii', 'iii', 'iv', 'v', 'ix', 'xiv', 'xl', 'xc', 'cd', 'mmxxvi'):
            with self.subTest(label=label):
                codes = ['000011'] + [mapping[c] for c in label] + ['010011', '000000', '101000', '\n']
                result = translate_detailed(codes)
                self.assertEqual(result['text'], label + '. ක\n')
                self.assertEqual(len(result['warnings']), 1)
                self.assertEqual(result['warnings'][0]['index'], 0)

    def test_indentation_and_newlines(self):
        codes = ['101000', '\n', '000000', '000011', '010100', '010011', '\n']
        self.assertEqual(translate_detailed(codes)['text'], 'ක\n i.\n')

    def test_unmarked_sinhala_and_ordinary_numbers_are_unchanged(self):
        codes = ['101000', '010100', '000000', '001111', '100000', '110000', '\n']
        self.assertEqual(translate_detailed(codes)['text'], 'කි 12\n')

    def test_incomplete_invalid_and_mid_sentence_labels_stay_unresolved(self):
        for codes in (['000011', '010100'],
                      ['000011'] + ['010100']*4 + ['010011'],
                      ['101000', '000000', '000011', '010100', '010011'],
                      ['000011', '010100', '010011', '101000']):
            with self.subTest(codes=codes):
                self.assertIn('�', translate_detailed(codes)['text'])

    def test_overrides_and_explicit_disable_are_respected(self):
        codes = ['000011', '010100', '010011']
        self.assertIn('�', translate_detailed(codes, roman_list_markers=False)['text'])
        result = translate_detailed(codes, overrides={1: 'CUSTOM'})
        self.assertIn('CUSTOM', result['text'])
        self.assertIn('�', result['text'])
