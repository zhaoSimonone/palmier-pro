#!/usr/bin/env python3
"""Apply a named tracked makeup look to a still or video."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from looks import resolve_look  # noqa: E402

DEFAULT_MODEL = SKILL_DIR / "assets" / "face_detection_yunet_2023mar.onnx"
LAYERS = ("warmth", "blush", "lips", "lids", "smooth")


def which_tool(name: str, explicit: str | None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"{name} not found: {explicit}")
        return str(path)
    found = shutil.which(name)
    if found:
        return found
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError(f"{name} not found on PATH")


def create_detector(model: Path, w: int, h: int, score: float = 0.6):
    if not model.is_file():
        raise FileNotFoundError(f"YuNet model missing: {model}")
    det = cv2.FaceDetectorYN_create(str(model), "", (w, h), score, 0.3, 5000)
    det.setInputSize((w, h))
    return det


def parse_face(face: np.ndarray) -> tuple[np.ndarray, float]:
    pts = face[4:14].reshape(5, 2).astype(np.float32)
    score = float(face[14]) if face.shape[0] > 14 else 1.0
    return pts, score


def yaw_from_pts(pts: np.ndarray) -> tuple[float, float]:
    reye, leye, nose = pts[0], pts[1], pts[2]
    mid = (reye[0] + leye[0]) * 0.5
    dist = float(np.linalg.norm(leye - reye)) + 1e-6
    return float((nose[0] - mid) / dist), dist


def cheek_centers(pts: np.ndarray, eye_dist: float) -> tuple[np.ndarray, np.ndarray]:
    reye, leye, nose, rmouth, lmouth = pts
    right = np.array(
        [
            reye[0] * 0.50 + rmouth[0] * 0.50 - eye_dist * 0.10,
            nose[1] * 0.28 + rmouth[1] * 0.72,
        ],
        np.float32,
    )
    left = np.array(
        [
            leye[0] * 0.50 + lmouth[0] * 0.50 + eye_dist * 0.10,
            nose[1] * 0.28 + lmouth[1] * 0.72,
        ],
        np.float32,
    )
    return right, left


def gaussian_blob(h: int, w: int, cx: float, cy: float, sx: float, sy: float, rot: float = 0.0) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xs - cx
    dy = ys - cy
    if abs(rot) > 1e-4:
        c, s = np.cos(rot), np.sin(rot)
        dx, dy = c * dx + s * dy, -s * dx + c * dy
    return np.exp(-0.5 * ((dx / (sx + 1e-6)) ** 2 + (dy / (sy + 1e-6)) ** 2))


def skin_gate(bgr: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(bgr.astype(np.float32))
    gate = (r > 70) & (g > 35) & (r > b * 0.95) & (r > g * 0.85) & ((r - b) > 8)
    return gate.astype(np.float32)


def add_bgr(img: np.ndarray, mask: np.ndarray, bgr: tuple[float, float, float], amount: float) -> None:
    if amount <= 0:
        return
    img[:, :, 0] += mask * (bgr[0] * amount)
    img[:, :, 1] += mask * (bgr[1] * amount)
    img[:, :, 2] += mask * (bgr[2] * amount)


def apply_look_to_bgr(
    bgr: np.ndarray,
    pts: np.ndarray,
    look: dict,
    strength: float,
    layers: set[str],
) -> np.ndarray:
    h, w = bgr.shape[:2]
    yaw, eye_dist = yaw_from_pts(pts)
    pad = int(eye_dist * 2.4)
    xs = np.clip(pts[:, 0], 0, w - 1)
    ys = np.clip(pts[:, 1], 0, h - 1)
    x0 = int(max(0, xs.min() - pad))
    y0 = int(max(0, ys.min() - pad))
    x1 = int(min(w, xs.max() + pad))
    y1 = int(min(h, ys.max() + pad))
    roi = bgr[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rh < 8 or rw < 8:
        return bgr

    local = pts.copy()
    local[:, 0] -= x0
    local[:, 1] -= y0
    r_cheek, l_cheek = cheek_centers(local, eye_dist)
    r_vis = float(np.clip(1.0 - max(0.0, -yaw) * 1.35, 0.12, 1.0))
    l_vis = float(np.clip(1.0 - max(0.0, yaw) * 1.35, 0.12, 1.0))
    rot = float(np.arctan2(local[1][1] - local[0][1], local[1][0] - local[0][0]))
    sx = eye_dist * float(look["cheek_sx"])
    sy = eye_dist * float(look["cheek_sy"])

    blush = gaussian_blob(rh, rw, r_cheek[0], r_cheek[1], sx, sy, rot) * r_vis
    blush += gaussian_blob(rh, rw, l_cheek[0], l_cheek[1], sx, sy, rot) * l_vis
    blush += gaussian_blob(
        rh, rw, local[2][0], local[2][1] + eye_dist * 0.06, eye_dist * 0.16, eye_dist * 0.10, rot
    ) * float(look["nose_blush"])
    blush = np.clip(blush, 0, 1)

    reye, leye, _nose, rmouth, lmouth = local
    mouth_c = (rmouth + lmouth) * 0.5
    lip_w = max(float(np.linalg.norm(lmouth - rmouth)) * 0.62, eye_dist * 0.28)
    lip_h = max(eye_dist * 0.16, 8.0)
    lips = gaussian_blob(rh, rw, mouth_c[0], mouth_c[1] + lip_h * 0.18, lip_w, lip_h, rot)
    lids = gaussian_blob(rh, rw, reye[0], reye[1] - eye_dist * 0.02, eye_dist * 0.22, eye_dist * 0.10, rot)
    lids += gaussian_blob(rh, rw, leye[0], leye[1] - eye_dist * 0.02, eye_dist * 0.22, eye_dist * 0.10, rot)
    lids = np.clip(lids, 0, 1)

    face = np.clip(
        gaussian_blob(rh, rw, float(local[:, 0].mean()), float(local[:, 1].mean()), eye_dist * 1.35, eye_dist * 1.75, rot),
        0,
        1,
    )
    skin = skin_gate(roi)
    blush *= skin
    face *= np.clip(skin + 0.15, 0, 1)
    lids *= skin

    img = roi.astype(np.float32)
    if "warmth" in layers:
        add_bgr(img, face, look["warm_bgr"], float(look["warm"]) * strength)
    if "blush" in layers:
        add_bgr(img, blush, look["blush_bgr"], float(look["blush"]) * strength)
    if "lips" in layers:
        add_bgr(img, lips, look["lips_bgr"], float(look["lips"]) * strength)
    if "lids" in layers:
        add_bgr(img, lids, look["lids_bgr"], float(look["lids"]) * strength)

    out = np.clip(img, 0, 255).astype(np.uint8)
    if "smooth" in layers and strength > 0:
        smooth = cv2.bilateralFilter(out, d=7, sigmaColor=26, sigmaSpace=7)
        alpha = (face * float(look["smooth"]) * strength).astype(np.float32)[..., None]
        out = np.clip(out.astype(np.float32) * (1 - alpha) + smooth.astype(np.float32) * alpha, 0, 255).astype(np.uint8)

    result = bgr.copy()
    result[y0:y1, x0:x1] = out
    return result


def smooth_pts(prev: np.ndarray | None, cur: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    if prev is None:
        return cur
    return prev * (1 - alpha) + cur * alpha


def parse_layers(raw: str | None, look: dict) -> set[str]:
    if not raw:
        return set(look["layers"])
    parts = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [item for item in parts if item not in LAYERS]
    if unknown:
        raise ValueError(f"unknown layers {unknown}; allowed: {', '.join(LAYERS)}")
    return set(parts)


def refuse_output(src: Path, dst: Path, force: bool) -> None:
    if src.resolve() == dst.resolve():
        raise ValueError("refusing to overwrite the input path")
    if dst.exists() and not force:
        raise FileExistsError(f"output exists: {dst} (pass --force to replace)")


def detect_pts(detector, image: np.ndarray) -> np.ndarray | None:
    _retval, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        return None
    pts, score = parse_face(faces[0])
    if score < 0.55:
        return None
    return pts


def process_image(src: Path, dst: Path, look: dict, strength: float, layers: set[str], model: Path) -> None:
    image = cv2.imread(str(src))
    if image is None:
        raise ValueError(f"cannot read image: {src}")
    h, w = image.shape[:2]
    pts = detect_pts(create_detector(model, w, h), image)
    if pts is None:
        raise ValueError(f"no face: {src}")
    out = apply_look_to_bgr(image, pts, look, strength, layers)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(dst), out, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise RuntimeError(f"failed to write {dst}")


def process_video(
    src: Path,
    dst: Path,
    look: dict,
    strength: float,
    layers: set[str],
    model: Path,
    ffmpeg: str,
) -> None:
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {src}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    detector = create_detector(model, w, h)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
        "-i", str(src),
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "libx264", "-crf", "16", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(dst),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    prev = None
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            pts = detect_pts(detector, frame)
            if pts is not None:
                pts = smooth_pts(prev, pts, 0.55)
                prev = pts
            else:
                pts = prev
            if pts is not None:
                frame = apply_look_to_bgr(frame, pts, look, strength, layers)
            proc.stdin.write(frame.tobytes())
            i += 1
            if i % 30 == 0:
                print(f"frame {i}/{n}", flush=True)
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
        rc = proc.wait()
    if rc != 0:
        print(err[-4000:], file=sys.stderr)
        raise RuntimeError(f"ffmpeg failed: {rc}")
    print(f"wrote {i} frames -> {dst}")


def render_label(text: str, path: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    fonts = (
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    )
    font = None
    for candidate in fonts:
        if Path(candidate).is_file():
            try:
                font = ImageFont.truetype(candidate, 64)
                break
            except OSError:
                continue
    if font is None:
        return None
    dummy = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 28, 16
    img = Image.new("RGBA", (tw + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=16, fill=(0, 0, 0, 150))
    draw.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return path


def write_compare(before: Path, after: Path, dest: Path, ffmpeg: str, force: bool) -> None:
    refuse_output(before, dest, force)
    if after.resolve() == dest.resolve():
        raise ValueError("compare path must differ from the treated video")
    label_dir = dest.parent / f".{dest.stem}-labels"
    label_dir.mkdir(parents=True, exist_ok=True)
    before_label = render_label("处理前", label_dir / "before.png")
    after_label = render_label("处理后", label_dir / "after.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if before_label and after_label:
        filt = "[0:v][2:v]overlay=40:48[left];[1:v][3:v]overlay=40:48[right];[left][right]hstack=inputs=2[v]"
        cmd = [
            ffmpeg, "-y",
            "-i", str(before), "-i", str(after),
            "-i", str(before_label), "-i", str(after_label),
            "-filter_complex", filt,
            "-map", "[v]", "-map", "0:a:0?",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(dest),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-i", str(before), "-i", str(after),
            "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
            "-map", "[v]", "-map", "0:a:0?",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(dest),
        ]
    subprocess.run(cmd, check=True)
    print(f"compare -> {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a tracked makeup look to a still or video.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--look", default="warm-peach")
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--layers")
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"input not found: {args.input}")
    if not np.isfinite(args.strength) or args.strength < 0:
        raise SystemExit("--strength must be a finite number >= 0")
    look = resolve_look(args.look)
    layers = parse_layers(args.layers, look)
    refuse_output(args.input, args.output, args.force)

    suffix = args.input.suffix.lower()
    print(f"look {look['display_name']} ({look['id']}) strength={args.strength} layers={','.join(sorted(layers))}")
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        process_image(args.input, args.output, look, args.strength, layers, args.model)
    else:
        ffmpeg = which_tool("ffmpeg", args.ffmpeg)
        which_tool("ffprobe", args.ffprobe)
        process_video(args.input, args.output, look, args.strength, layers, args.model, ffmpeg)
        if args.compare:
            write_compare(args.input, args.output, args.compare, ffmpeg, args.force)


if __name__ == "__main__":
    try:
        main()
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
