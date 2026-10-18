import unittest
from services.page_validation import page_crop_box


class PageValidationTests(unittest.TestCase):
    def test_missing_page_requires_retake_by_default(self):
        with self.assertRaisesRegex(ValueError, 'Retake the photo'):
            page_crop_box([], 1080, 1920)

    def test_full_image_fallback_requires_explicit_opt_in(self):
        box, warnings = page_crop_box([], 1080, 1920, allow_full_image=True)
        self.assertEqual(box, [0, 0, 1080, 1920])
        self.assertEqual(len(warnings), 1)

    def test_valid_box_rounds_outward_and_clamps_to_image(self):
        box, warnings = page_crop_box([[-3.4, 10.7, 1200, 1900.2]], 1080, 1920)
        self.assertEqual(box, [0, 10, 1080, 1901])
        self.assertEqual(warnings, [])

    def test_invalid_and_empty_crops_are_rejected(self):
        for box in ([30, 0, 10, 50], [float('nan'), 0, 10, 50], [1, 2, 3]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                page_crop_box([box], 100, 100)
