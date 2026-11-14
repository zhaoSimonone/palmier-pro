import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location('korean_holy_light',
                                              SCRIPTS / 'korean_holy_light.py')
korean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(korean)

blur_spec = importlib.util.spec_from_file_location('blur_censor_for_look',
                                                   SCRIPTS / 'blur_censor.py')
censor = importlib.util.module_from_spec(blur_spec)
blur_spec.loader.exec_module(censor)


class KoreanLightTests(unittest.TestCase):
    def test_wide_light_covers_both_sides_and_fades_at_the_corners(self):
        alpha, sticker = korean.build_korean_holy_light(200, 110, 0.90, '')
        height, width = alpha.shape
        self.assertEqual(sticker.shape, (height, width, 4))
        self.assertGreaterEqual(float(alpha.min()), 0.0)
        self.assertLessEqual(float(alpha.max()), 0.94)
        self.assertGreater(float(alpha[height // 2, width // 2]), 0.6)
        self.assertGreater(float(alpha[height // 2, int(width * 0.30)]), 0.6)
        self.assertGreater(float(alpha[height // 2, int(width * 0.70)]), 0.6)
        self.assertLess(float(alpha[0, 0]), 0.1)

    def test_compact_light_leaves_the_middle_and_the_waist_alone(self):
        alpha, _ = korean.build_korean_holy_light(200, 110, 0.87, '', compact=True)
        height, width = alpha.shape
        self.assertLess(float(alpha[height // 2, width // 2]), 0.5)
        self.assertGreater(float(alpha[height // 2, int(width * 0.30)]), 0.7)
        self.assertGreater(float(alpha[height // 2, int(width * 0.70)]), 0.7)
        self.assertLess(float(alpha[int(height * 0.10), width // 2]), 0.05)

    def test_lettering_stays_solid_where_the_light_is_weak(self):
        font = korean.resolve_korean_font()
        if font is None:
            self.skipTest('no Korean handwriting font installed')
        alpha, sticker = korean.build_korean_holy_light(
            200, 110, 0.87, korean.DEFAULT_TEXT, compact=True, font=font)
        solid = sticker[..., 3] > 200
        self.assertGreater(int(solid.sum()), 500)
        weak_light = alpha < 0.5
        self.assertGreater(int((solid & weak_light).sum()), 50)

    def test_apply_is_in_place_and_leaves_the_corner_untouched(self):
        alpha, sticker = korean.build_korean_holy_light(60, 40, 0.90, '')
        frame = np.full((160, 200, 3), 80, np.uint8)
        original = frame.copy()
        returned = korean.apply_korean_holy_light(frame, 100.0, 80.0, alpha, sticker,
                                                  blur_sigma=0.0)
        self.assertIsNone(returned)
        self.assertEqual(frame.dtype, np.uint8)
        self.assertEqual(frame.shape, original.shape)
        self.assertGreater(int(frame[80, 100].mean()), 80)
        np.testing.assert_array_equal(frame[0, 0], original[0, 0])

    def test_apply_clips_a_light_larger_than_the_frame(self):
        alpha, sticker = korean.build_korean_holy_light(200, 160, 0.90, '')
        frame = np.zeros((60, 80, 3), np.uint8)
        korean.apply_korean_holy_light(frame, 0.0, 0.0, alpha, sticker, blur_sigma=0.0)
        self.assertEqual(frame.shape, (60, 80, 3))
        self.assertGreater(int(frame.mean()), 0)

    def test_rejects_invalid_geometry_and_strength(self):
        for rx, ry, strength in ((0, 100, 0.9), (100, -1, 0.9),
                                 (100, 100, 0.0), (100, 100, 1.4)):
            with self.subTest(rx=rx, ry=ry, strength=strength):
                with self.assertRaises(ValueError):
                    korean.build_korean_holy_light(rx, ry, strength, '')

    def test_missing_font_fails_only_when_lettering_is_requested(self):
        with patch.object(korean, 'resolve_korean_font', return_value=None):
            with self.assertRaises(ValueError):
                korean.build_korean_holy_light(100, 60, 0.9, 'text')
            alpha, _ = korean.build_korean_holy_light(100, 60, 0.9, '')
            self.assertGreater(float(alpha.max()), 0.5)


class KoreanArgumentTests(unittest.TestCase):
    def test_look_is_opt_in_and_defaults_to_none(self):
        with patch.object(sys, 'argv', ['blur_censor', '--input', 'in.mp4',
                                        '--output', 'out.mp4']):
            args = censor.parse_args()
        self.assertIsNone(args.sticker_look)
        self.assertFalse(args.sticker_style)
        self.assertIsNone(args.glow)
        self.assertIsNone(args.glow_scale)
        self.assertEqual(args.holy_size, 'auto')

    def test_compact_requires_the_korean_look(self):
        argv = ['blur_censor', '--input', 'in.mp4', '--output', 'out.mp4',
                '--sticker-compact']
        with patch.object(sys, 'argv', argv), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'exists', return_value=False):
            with self.assertRaises(ValueError):
                censor.main()

    def test_invalid_holy_size_is_rejected_before_probing(self):
        argv = ['blur_censor', '--input', 'in.mp4', '--output', 'out.mp4',
                '--sticker-look', 'korean', '--holy-size', '10,-5']
        with patch.object(sys, 'argv', argv), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'exists', return_value=False):
            with self.assertRaises(ValueError):
                censor.main()


if __name__ == '__main__':
    unittest.main()
