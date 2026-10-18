import unittest
from services.pipeline_config import grid_config_for_vision


class PipelineConfigTests(unittest.TestCase):
    def test_two_class_model_resolves_back_zero(self):
        vision = {'front_class_id': 1, 'class_names': {'0': 'back', '1': 'front'}}
        settings = {'recover_back_dots': True}
        config = grid_config_for_vision(vision, settings)
        self.assertEqual((config.front_class_id, config.back_class_id), (1, 0))
        self.assertEqual(settings, {'recover_back_dots': True})

    def test_ambiguous_names_need_explicit_configuration(self):
        vision = {'front_class_id': 2, 'class_names': ['other', 'unknown', 'front']}
        with self.assertRaises(ValueError):
            grid_config_for_vision(vision, {'recover_back_dots': True})
        config = grid_config_for_vision(vision, {'recover_back_dots': True, 'back_class_id': 1})
        self.assertEqual(config.back_class_id, 1)
        with self.assertRaises(ValueError):
            grid_config_for_vision(vision, {'recover_back_dots': True, 'back_class_id': 7})

    def test_legacy_labels_keep_existing_default(self):
        self.assertEqual(grid_config_for_vision({}, {'recover_back_dots': True}).back_class_id, 1)

