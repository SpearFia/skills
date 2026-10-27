"""Measure a downloaded clip for the media-search checks and print JSON.

Usage:
  python qc.py CLIP [--frames OUT_DIR]   measure CLIP; optionally save 4 sample frames
  python qc.py --self-test               build synthetic clips and check the flags

Needs ffmpeg and ffprobe on PATH. Standard library only. The script flags; the agent
decides (see references/checks.md).
"""

import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 160, 90  # analysis size
SAMPLES = 12
CORNER = 0.2  # corner box: 20% of width and height


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=False)


def probe(path):
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
               "-show_format", str(path)])
    if out.returncode:
        raise SystemExit(f"ffprobe failed: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not video:
        raise SystemExit("No video stream.")
    num, _, den = video.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    duration = float(video.get("duration") or data["format"].get("duration") or 0)
    bitrate = float(video.get("bit_rate") or data["format"].get("bit_rate") or 0)
    w, h = int(video["width"]), int(video["height"])
    bpp = bitrate / (w * h * fps) if w and h and fps else 0.0
    return {"width": w, "height": h, "fps": round(fps, 3), "duration": round(duration, 3),
            "bitrate": int(bitrate), "bits_per_pixel": round(bpp, 4)}


def black_ratio(path, duration):
    err = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
               "blackdetect=d=0.1:pix_th=0.10", "-an", "-f", "null", "-"]).stderr
    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", err))
    return round(black / duration, 3) if duration else 0.0


def crop(path, w, h):
    err = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
               "fps=2,cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"]).stderr
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
    if not found:
        return None
    cw, ch, cx, cy = (int(v) for v in found[-1])
    # Ignore trims of a few pixels (encoder edges).
    if w - cw <= max(8, w // 50) and h - ch <= max(8, h // 50):
        return None
    return {"w": cw, "h": ch, "x": cx, "y": cy}


def gray_frames(path, duration):
    rate = SAMPLES / duration if duration else 1
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                          f"fps={rate},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=False).stdout
    size = W * H
    return [out[i:i + size] for i in range(0, len(out) - size + 1, size)][:SAMPLES]


def region(x0, y0, x1, y1):
    return [y * W + x for y in range(int(y0), int(y1)) for x in range(int(x0), int(x1))]


def spreads(frames, pixels):
    """Each pixel's brightness spread across frames."""
    return [statistics.pstdev(f[p] for f in frames) for p in pixels]


def still_share(spread):
    return sum(s < 3 for s in spread) / len(spread)


def static_corners(frames, crop_box, src_w, src_h):
    """Corners whose detail stays put while the centre moves: likely logos."""
    if len(frames) < 4:
        return [], False
    # Analyse inside the picture, not in letterbox bars.
    if crop_box:
        sx, sy = W / src_w, H / src_h
        x0, y0 = crop_box["x"] * sx, crop_box["y"] * sy
        x1, y1 = x0 + crop_box["w"] * sx, y0 + crop_box["h"] * sy
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    cw, ch = (x1 - x0) * CORNER, (y1 - y0) * CORNER
    centre = spreads(frames, region(x0 + cw, y0 + ch, x1 - cw, y1 - ch))
    frozen = statistics.fmean(centre) < 2
    centre_still = still_share(centre)
    corners = {
        "top_left": region(x0, y0, x0 + cw, y0 + ch),
        "top_right": region(x1 - cw, y0, x1, y0 + ch),
        "bottom_left": region(x0, y1 - ch, x0 + cw, y1),
        "bottom_right": region(x1 - cw, y1 - ch, x1, y1),
    }
    flagged = []
    for name, pixels in corners.items():
        spread = spreads(frames, pixels)
        still = [p for p, s in zip(pixels, spread) if s < 3]
        if frozen or len(still) < 8:
            continue
        # A logo is a still patch with edges, in a corner of a moving picture (a locked-off
        # shot is still everywhere, a flat sky has no edges).
        detail = statistics.pstdev(statistics.fmean(f[p] for f in frames) for p in still)
        share = still_share(spread)
        if share >= 0.15 and share > 3 * centre_still + 0.05 and detail > 8:
            flagged.append(name)
    return flagged, frozen


def save_frames(path, duration, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i in range(4):
        t = duration * (i + 0.5) / 4
        target = out_dir / f"{Path(path).stem}_{i + 1}.jpg"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path),
             "-frames:v", "1", "-vf", "scale=640:-2", str(target)])
        if target.exists():
            saved.append(str(target))
    return saved


def measure(path, frames_dir=None):
    info = probe(path)
    info["black_ratio"] = black_ratio(path, info["duration"])
    info["crop"] = crop(path, info["width"], info["height"])
    corners, frozen = static_corners(gray_frames(path, info["duration"]), info["crop"],
                                     info["width"], info["height"])
    info["static_corners"] = corners
    info["frozen"] = frozen
    if frames_dir:
        info["frames"] = save_frames(path, info["duration"], frames_dir)
    return info


def self_test():
    life = "life=s=640x360:mold=10:r=25:ratio=0.3:death_color=#202020:life_color=#e0e0e0"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def make(name, *args):
            target = tmp / name
            out = run(["ffmpeg", "-v", "error", "-y", *args, "-t", "4", "-pix_fmt", "yuv420p",
                       str(target)])
            assert out.returncode == 0, out.stderr
            return target

        clean = make("clean.mp4", "-f", "lavfi", "-i", life)
        logo = make("logo.mp4", "-f", "lavfi", "-i", life, "-f", "lavfi", "-i",
                    "testsrc=s=96x54:d=4", "-filter_complex",
                    "[1:v]trim=end_frame=1,loop=loop=-1:size=1[l];[0:v][l]overlay=W-w-8:8")
        bars = make("bars.mp4", "-f", "lavfi", "-i", life, "-vf",
                    "scale=640:270,pad=640:360:0:45:black")

        c = measure(clean, tmp / "frames")
        assert c["height"] == 360 and c["crop"] is None, c
        assert c["static_corners"] == [] and not c["frozen"], c
        assert len(c["frames"]) == 4, c
        w = measure(logo)
        assert w["static_corners"] == ["top_right"], w
        b = measure(bars)
        assert b["crop"] is not None and b["crop"]["h"] <= 280, b
        assert b["static_corners"] == [], b
    print("self-test passed")


def main(argv):
    if argv == ["--self-test"]:
        self_test()
        return
    if not argv or argv[0].startswith("-"):
        raise SystemExit(__doc__)
    frames_dir = None
    if "--frames" in argv:
        i = argv.index("--frames")
        frames_dir = argv[i + 1]
    print(json.dumps(measure(argv[0], frames_dir), indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
