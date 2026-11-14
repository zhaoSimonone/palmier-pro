import importlib.util
import os
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'blur_censor.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('blur_censor', SCRIPT)
censor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(censor)

FFMPEG = os.environ.get('FFMPEG') or shutil.which('ffmpeg')
FFPROBE = os.environ.get('FFPROBE') or shutil.which('ffprobe')

WIDTH, HEIGHT, FRAMES, FPS = 160, 120, 10, 10


def skin_bgr(value):
    return cv2.cvtColor(np.uint8([[[28, 100, value]]]), cv2.COLOR_HSV2BGR)[0][0]


def make_frame(index):
    """White stage with a moving skin-toned checkerboard block."""
    image = np.full((HEIGHT, WIDTH, 3), 245, np.uint8)
    left = 20 + index * 8
    top = (HEIGHT - 40) // 2
    light, dark = skin_bgr(180), skin_bgr(140)
    grid = (np.add.outer(np.arange(40), np.arange(40)) // 10) % 2
    tile = np.where(grid[..., None] == 0, light, dark)
    image[top:top + 40, left:left + 40] = tile
    return image


class ArgumentTests(unittest.TestCase):
    def test_defaults_match_the_validated_recipe(self):
        with patch.object(sys, 'argv', ['blur_censor', '--input', 'in.mp4', '--output', 'out.mp4']):
            args = censor.parse_args()
        self.assertEqual(args.blur, 0.30)
        self.assertEqual(args.zone_width, 0.95)
        self.assertEqual(args.zone_height, 0.85)
        self.assertEqual(args.plateau, 0.78)
        self.assertEqual(args.milk, 2.0)
        self.assertEqual(args.core, 0.0)
        self.assertEqual(args.sigma_max, 26.0)
        self.assertEqual(args.min_area, 0)

    def test_parse_rect_rejects_non_positive_size(self):
        for text in ('1,2,0,4', '1,2,4,-1', '1,2,4'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    censor.parse_rect(text, '--region')

    def test_parse_rect_reads_four_numbers(self):
        self.assertEqual(censor.parse_rect('10,20,30,40', '--region'), (10.0, 20.0, 30.0, 40.0))

    def test_parse_pair_rejects_non_finite(self):
        with self.assertRaises(ValueError):
            censor.parse_pair('nan,1', '--seed')

    def test_offset_defaults_to_zero_and_parses_a_shift(self):
        with patch.object(sys, 'argv', ['blur_censor', '--input', 'in.mp4', '--output', 'out.mp4']):
            args = censor.parse_args()
        self.assertEqual(args.offset, '0,0')
        self.assertEqual(censor.parse_pair('20,10', '--offset'), (20.0, 10.0))

    def test_parse_segment_reads_every_field(self):
        seg = censor.parse_segment(
            'start=3.2;end=6.4;region=270,500,160,130;offset=20,40;smooth=12',
            '--segment[0]', 2.0)
        self.assertEqual(seg['start'], 3.2)
        self.assertEqual(seg['end'], 6.4)
        self.assertEqual(seg['rects'], [(270.0, 500.0, 160.0, 130.0)])
        self.assertEqual(seg['offset'], (20.0, 40.0))
        self.assertEqual(seg['smooth'], 12.0)
        self.assertEqual(seg['seeds'], [])

    def test_parse_segment_defaults_and_rejects_bad_input(self):
        seg = censor.parse_segment('start=1;end=2;region=1,2,3,4', '--segment', 2.0)
        self.assertEqual(seg['offset'], (0.0, 0.0))
        self.assertEqual(seg['smooth'], 2.0)
        for text in ('start=1;end=2', 'start=1;end=2;region=1,2,3',
                     'start=1;end=2;region=1,2,0,4',
                     'start=1;end=2;region=1,2,3,4;smooth=-1'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    censor.parse_segment(text, '--segment', 2.0)

    def test_build_segments_orders_intervals_and_rejects_overlap(self):
        base = ['blur_censor', '--input', 'in.mp4', '--output', 'out.mp4']
        with patch.object(sys, 'argv', base + [
                '--segment', 'start=6;end=8;region=1,2,3,4',
                '--segment', 'start=1;end=3;region=1,2,3,4']):
            args = censor.parse_args()
        segments = censor.build_segments(args, 10.0, 100, 10.0, (0.0, 0.0))
        self.assertEqual([(s['first'], s['last']) for s in segments], [(10, 30), (60, 80)])
        with patch.object(sys, 'argv', base + [
                '--segment', 'start=1;end=5;region=1,2,3,4',
                '--segment', 'start=4;end=8;region=1,2,3,4']):
            overlapping = censor.parse_args()
        with self.assertRaises(ValueError):
            censor.build_segments(overlapping, 10.0, 100, 10.0, (0.0, 0.0))


class MaskTests(unittest.TestCase):
    def test_skin_mask_selects_skin_and_rejects_white_and_red(self):
        image = np.full((40, 40, 3), 245, np.uint8)
        image[10:30, 10:30] = skin_bgr(180)
        image[10:30, 30:40] = (0, 0, 220)
        mask = censor.skin_mask(image, (5, 34), (85, 180), (120, 250))
        self.assertGreater(mask[15:25, 15:25].mean(), 200)
        self.assertLess(mask[15:25, 32:38].mean(), 60)
        self.assertLess(mask[33:38, 15:25].mean(), 60)

    def test_component_at_picks_the_component_under_the_seed(self):
        mask = np.zeros((100, 200), np.uint8)
        mask[10:40, 10:50] = 255
        mask[60:95, 150:195] = 255
        box = censor.component_at(mask, 30.0, 25.0, (0, 0, 200, 100), None, 10, 200)
        self.assertIsNotNone(box)
        self.assertEqual((box['x'], box['y'], box['w'], box['h']), (10, 10, 40, 30))

    def test_component_at_band_separates_neighbours(self):
        mask = np.zeros((60, 120), np.uint8)
        mask[10:50, 10:60] = 255
        mask[10:50, 60:110] = 255
        merged = censor.component_at(mask, 30.0, 30.0, (0, 0, 120, 60), None, 10, 200)
        split = censor.component_at(mask, 30.0, 30.0, (0, 0, 120, 60), (60, 120), 10, 200)
        self.assertEqual(merged['w'], 100)
        self.assertEqual(split['w'], 50)


class GeometryTests(unittest.TestCase):
    def test_ellipse_mask_plateaus_then_feathers_to_zero(self):
        mask = censor.ellipse_mask(0, 0, 100, 100, 50.0, 50.0, 40.0, 50.0, 0.55)
        self.assertGreater(mask[50, 50], 0.99)
        self.assertGreater(mask[50, 72], 0.99)
        self.assertAlmostEqual(float(mask[50, 90]), 0.0, places=5)

    def test_smooth_track_fills_gaps_from_the_previous_box(self):
        box = {'x': 1, 'y': 1, 'w': 10, 'h': 10, 'area': 100, 'cx': 5.0, 'cy': 5.0}
        filled = censor.smooth_track([None, box, None], 0.0)
        self.assertEqual(len(filled), 3)
        self.assertEqual(filled[2]['cx'], 5.0)
        self.assertEqual(filled[0]['cx'], 0.0)

    def test_smooth_track_damps_a_single_frame_jitter(self):
        base = {'x': 0, 'y': 0, 'w': 10, 'h': 10, 'area': 100, 'cx': 50.0, 'cy': 50.0}
        track = [dict(base) for _ in range(9)]
        track[4] = dict(base, cx=90.0)
        smoothed = censor.smooth_track(track, 2.0)
        self.assertLess(abs(smoothed[4]['cx'] - 50.0), 20.0)
        self.assertGreater(abs(smoothed[4]['cx'] - 50.0), 0.0)

    def test_smooth_track_keeps_a_steady_position_steady(self):
        base = {'x': 0, 'y': 0, 'w': 10, 'h': 10, 'area': 100, 'cx': 50.0, 'cy': 70.0}
        smoothed = censor.smooth_track([dict(base) for _ in range(9)], 2.0)
        for box in smoothed:
            self.assertAlmostEqual(box['cx'], 50.0, places=5)
            self.assertAlmostEqual(box['cy'], 70.0, places=5)


class StickerGlowTests(unittest.TestCase):
    def test_glow_is_opaque_at_centre_and_fades_to_zero(self):
        alpha, sticker = censor.build_sticker_glow(120, 100, 1.3, 0.9, '喵~')
        height, width = alpha.shape
        self.assertGreater(alpha[height // 2, width // 2], 0.85)
        self.assertAlmostEqual(float(alpha[0, 0]), 0.0, places=3)
        self.assertEqual(sticker.shape, (height, width, 4))
        self.assertGreater(int(sticker[..., 3].max()), 0)

    def test_glow_whitens_the_tracked_centre_without_touching_the_corner(self):
        frame = np.full((200, 200, 3), 60, np.uint8)
        alpha, sticker = censor.build_sticker_glow(40, 35, 1.3, 0.9, '')
        censor.apply_sticker_glow(frame, 100.0, 100.0, alpha, sticker, 1.0)
        self.assertGreater(float(frame[100, 100].mean()), 180)
        self.assertEqual(int(frame[0, 0].mean()), 60)


@unittest.skipUnless(FFMPEG and FFPROBE, 'FFmpeg and ffprobe required')
class RenderTests(unittest.TestCase):
    def build_source(self, root):
        frames = root / 'frames'
        frames.mkdir()
        for index in range(FRAMES):
            cv2.imwrite(str(frames / f'{index + 1:04d}.png'), make_frame(index))
        source = root / 'source.mp4'
        subprocess.run([FFMPEG, '-v', 'error', '-y', '-framerate', str(FPS),
                        '-i', str(frames / '%04d.png'),
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-shortest', str(source)], check=True)
        return source

    def test_blur_reduces_roi_contrast_and_preserves_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.build_source(root)
            output = root / 'output.mp4'
            command = [sys.executable, str(SCRIPT), '--input', str(source), '--output', str(output),
                       '--seed', '40,60', '--blur', '0.20', '--zone-width', '1.50',
                       '--zone-height', '1.08', '--plateau', '0.55', '--milk', '2.0',
                       '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            streams = censor.probe(FFPROBE, output)['streams']
            self.assertEqual([s['codec_type'] for s in streams], ['video', 'audio'])
            video = next(s for s in streams if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (WIDTH, HEIGHT))
            self.assertEqual(int(video['nb_frames']), FRAMES)
            self.assertEqual(float(Fraction(video['r_frame_rate'])), float(FPS))

            def frame_at(path, index):
                raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(path), '-f', 'rawvideo',
                                      '-pix_fmt', 'bgr24', '-'], check=True, capture_output=True).stdout
                return np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)[index]

            source_frame = frame_at(source, 5)
            output_frame = frame_at(output, 5)
            left = 20 + 5 * 8 + 10
            top = (HEIGHT - 40) // 2 + 10
            roi = (slice(top, top + 20), slice(left, left + 20))
            before = source_frame[roi].max(axis=2).std()
            after = output_frame[roi].max(axis=2).std()
            self.assertGreater(before, 10.0)
            self.assertLess(after, before / 3.0)

            before_bytes = output.read_bytes()
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(before_bytes, output.read_bytes())
            self.assertFalse(list(root.glob('.blur-censor-*')))

    def test_template_region_mode_renders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.build_source(root)
            output = root / 'region.mp4'
            command = [sys.executable, str(SCRIPT), '--input', str(source), '--output', str(output),
                       '--region', '30,40,40,40', '--blur', '0.20',
                       '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertFalse(list(root.glob('.blur-censor-*')))

    def test_two_segments_render_with_an_untouched_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.build_source(root)
            output = root / 'two_segments.mp4'
            command = [sys.executable, str(SCRIPT), '--input', str(source), '--output', str(output),
                       '--segment', 'start=0;end=0.4;region=30,40,40,40',
                       '--segment', 'start=0.6;end=1.0;region=30,40,40,40',
                       '--blur', '0.20', '--zone-width', '1.0', '--zone-height', '1.0',
                       '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            video = next(s for s in censor.probe(FFPROBE, output)['streams']
                         if s['codec_type'] == 'video')
            self.assertEqual(int(video['nb_frames']), FRAMES)

            def frame_at(path, index):
                raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(path), '-f', 'rawvideo',
                                      '-pix_fmt', 'bgr24', '-'], check=True,
                                     capture_output=True).stdout
                return np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)[index].astype(np.float32)

            gap = float(np.abs(frame_at(source, 5) - frame_at(output, 5)).mean())
            first_segment = float(np.abs(frame_at(source, 1) - frame_at(output, 1)).mean())
            second_segment = float(np.abs(frame_at(source, 8) - frame_at(output, 8)).mean())
            self.assertLess(gap, 2.0)
            self.assertGreater(first_segment, gap)
            self.assertGreater(second_segment, gap)
            self.assertFalse(list(root.glob('.blur-censor-*')))


if __name__ == '__main__':
    unittest.main()
