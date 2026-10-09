#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_look import apply_look_to_bgr, parse_layers, refuse_output  # noqa: E402
from looks import resolve_look  # noqa: E402


class LookRegistryTests(unittest.TestCase):
    def test_warm_peach_aliases(self):
        look = resolve_look("轻薄暖桃妆")
        self.assertEqual(look["id"], "warm-peach")
        self.assertEqual(look["display_name"], "轻薄暖桃妆")
        self.assertEqual(resolve_look("peach")["id"], "warm-peach")

    def test_unknown_look(self):
        with self.assertRaises(ValueError):
            resolve_look("smoky")


class LayerAndPathTests(unittest.TestCase):
    def test_default_layers(self):
        look = resolve_look("warm-peach")
        self.assertEqual(parse_layers(None, look), set(look["layers"]))

    def test_blush_only(self):
        look = resolve_look("warm-peach")
        self.assertEqual(parse_layers("blush", look), {"blush"})

    def test_refuse_same_path(self):
        path = Path("/tmp/video-face-makeup-same.mp4")
        with self.assertRaises(ValueError):
            refuse_output(path, path, force=True)

    def test_refuse_existing_without_force(self):
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "in.mp4"
            dst = Path(raw) / "out.mp4"
            src.write_bytes(b"x")
            dst.write_bytes(b"y")
            with self.assertRaises(FileExistsError):
                refuse_output(src, dst, force=False)
            refuse_output(src, dst, force=True)


class OverlayTests(unittest.TestCase):
    def test_blush_raises_cheek_red(self):
        look = resolve_look("warm-peach")
        h, w = 240, 180
        image = np.zeros((h, w, 3), np.uint8)
        image[:] = (90, 130, 180)  # BGR skin-like
        pts = np.array(
            [
                [70.0, 80.0],
                [110.0, 80.0],
                [90.0, 100.0],
                [75.0, 125.0],
                [105.0, 125.0],
            ],
            np.float32,
        )
        out = apply_look_to_bgr(image, pts, look, 1.0, {"blush"})
        # right cheek in image-left, around (70, 115)
        before = image[115, 62].astype(np.int16)
        after = out[115, 62].astype(np.int16)
        self.assertGreater(int(after[2] - before[2]), 8)
        self.assertGreater(int(after[2] - after[0]), int(before[2] - before[0]))


if __name__ == "__main__":
    unittest.main()
