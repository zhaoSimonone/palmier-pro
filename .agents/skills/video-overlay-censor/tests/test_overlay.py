import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_overlay.py'
spec = importlib.util.spec_from_file_location('overlay', SCRIPT)
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


class GeometryTests(unittest.TestCase):
    def test_edge_cleanup_keeps_enclosed_white(self):
        pixels = np.full((9, 9, 4), 255, dtype=np.uint8)
        pixels[2:7, 2:7, :3] = 0
        pixels[4, 4, :3] = 255
        result = overlay.edge_connected_near_white_alpha(pixels)
        self.assertEqual(result[0, 0, 3], 0)
        self.assertEqual(result[4, 4, 3], 255)

    def test_fixed_size_movement_loop_and_half_open_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sprites = [Image.new('RGBA', (4, 4), color) for color in ('red', 'blue')]
            overlay.make_overlay_frames(root, 4, 6, (40, 20), sprites, [.25, .25],
                                        .25, 1.25, 8, 6, [(.25, 10, 10), (1.25, 26, 10)], 0)
            frames = [Image.open(p).copy() for p in sorted(root.glob('*.png'))]
            self.assertIsNone(frames[0].getbbox())
            self.assertIsNone(frames[5].getbbox())
            for index, frame in enumerate(frames[1:5]):
                left, top, right, bottom = frame.getbbox()
                self.assertEqual((right-left, bottom-top), (8, 6))
                self.assertEqual(left, 6+4*index)
                self.assertEqual(frame.getpixel((left, top))[:3], (255, 0, 0) if index % 2 == 0 else (0, 0, 255))

    def test_invalid_keyframes_rejected(self):
        cases = [[], {'keyframes': []}, {'keyframes': [{'time': 0, 'x': 1, 'y': 2}]*2},
                 {'keyframes': [{'time': 0, 'x': float('nan'), 'y': 2}, {'time': 1, 'x': 1, 'y': 2}]}]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'keys.json'
            for case in cases:
                with self.subTest(case=case):
                    path.write_text(json.dumps(case))
                    with self.assertRaises(ValueError):
                        overlay.parse_keyframes(path, None, None, 0, 1)


FFMPEG = os.environ.get('FFMPEG') or shutil.which('ffmpeg')
FFPROBE = os.environ.get('FFPROBE') or shutil.which('ffprobe')


@unittest.skipUnless(FFMPEG and FFPROBE, 'FFmpeg and ffprobe required')
class RenderTests(unittest.TestCase):
    def test_synthetic_render_preserves_audio_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, sticker, output = (root / n for n in ('input.mp4', 'cover.gif', 'output.mp4'))
            subprocess.run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=64x64:r=10:d=1',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264',
                            '-c:a', 'aac', '-shortest', str(source)], check=True)
            Image.new('RGB', (8, 8), 'red').save(sticker, save_all=True,
                append_images=[Image.new('RGB', (8, 8), 'blue')], duration=100, loop=0)
            command = [sys.executable, str(SCRIPT), '--input', str(source), '--overlay', str(sticker),
                       '--output', str(output), '--start', '.2', '--end', '.8', '--width', '16',
                       '--x', '32', '--y', '32', '--ffmpeg', FFMPEG, '--ffprobe', FFPROBE]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            streams = overlay.probe(FFPROBE, output)['streams']
            self.assertEqual([s['codec_type'] for s in streams], ['video', 'audio'])
            raw = subprocess.run([FFMPEG, '-v', 'error', '-i', str(output), '-f', 'rawvideo',
                                  '-pix_fmt', 'rgb24', '-'], check=True, capture_output=True).stdout
            frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 64, 64, 3)
            self.assertEqual(len(frames), 10)
            self.assertLess(int(frames[0, 32, 32].max()), 10)
            self.assertGreater(int(frames[2, 32, 32, 0]), 200)
            self.assertLess(int(frames[8, 32, 32].max()), 10)
            before = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(before, output.read_bytes())
            self.assertFalse(list(root.glob('.video-overlay-censor-*')))
            bad = command.copy()
            bad[bad.index('--output')+1] = str(root / 'failed.mp4')
            bad[bad.index('--ffmpeg')+1] = '/nonexistent/ffmpeg'
            self.assertNotEqual(subprocess.run(bad, capture_output=True).returncode, 0)
            self.assertFalse((root / 'failed.mp4').exists())
            self.assertFalse(list(root.glob('.video-overlay-censor-*')))


if __name__ == '__main__':
    unittest.main()
