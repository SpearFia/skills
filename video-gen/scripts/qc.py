# SPDX-License-Identifier: MIT OR Apache-2.0
"""Automatic quality checks for generated reference images, loop clips and audio.

Usage:
  python qc.py image REF.png
  python qc.py clip CLIP.mp4 [--no-voice]
  python qc.py audio CHUNK.wav [--no-voice]
  python qc.py --self-test

Each prints {"ok": bool, "fails": [...], "metrics": {...}} and exits 1 on a fail, so callers
can re-roll the seed. Thresholds are in LIMITS; they were set on the 2026-10-27 test clips in
D:\\SpearFia\\tests and are starting points, not measurements of viewer preference.

Voice detection runs faster-whisper from the voiceover skill's venv (WHISPER_PYTHON, default
D:/SpearFia/tools/whisper/Scripts/python.exe) on the CPU, so it doesn't fight ComfyUI for VRAM.
Without that venv the voice check is skipped and reported as such. Needs ffmpeg and ffprobe.
"""

import argparse
import array
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LIMITS = {
    "black_p30_max": 14,       # image: 30th percentile of max(R,G,B) must be this dark (0-255)
    # Clip seam and motion compare only lit pixels: SSIM over a mostly black frame stays high
    # however much the light moves, so it is reported but not judged.
    "seam_step_ratio_max": 3,  # clip: last->first jump vs the clip's typical frame step
    "motion_min": 0.06,        # clip: mean lit-pixel change from frame 0 (sizzle v1: 0.041)
    "flashes_per_s_max": 3,    # clip: WCAG 2.3.1 general flash threshold
    "flash_delta": 20,         # clip: mean-luma swing (0-255) that counts as a flash edge
    "flicker_max": 2.5,        # clip: mean local temporal jitter (0-255), boiling grain
    "peak_dbfs_max": -0.3,     # audio: sample peak; above this is clipping
    "burst_db_max": 24,        # audio: loudest 50 ms window over the median window
    "burst_floor_dbfs": -24,   # audio: ...only when that window is also this loud
    "dropout_s_max": 1.0,      # audio: longest silence (< -60 dBFS) inside the file
    "voice_words_max": 2,      # audio: confident whisper words allowed (hallucination slack)
}
WHISPER_PYTHON = os.environ.get("WHISPER_PYTHON", "D:/SpearFia/tools/whisper/Scripts/python.exe")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, check=False)


def ff(args):
    r = run(["ffmpeg", "-v", "error", *args])
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace").strip())
    return r.stdout


def raw(args):
    """ffmpeg output piped to stdout."""
    return ff([*args, "-"])


def report(fails, metrics):
    return {"ok": not fails, "fails": fails, "metrics": metrics}


def percentile(values, q):
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


# ---- reference image ------------------------------------------------------------------

def check_image(path):
    px = raw(["-i", str(path), "-vf", "scale=192:108", "-f", "rawvideo", "-pix_fmt", "rgb24"])
    lum = [max(px[i], px[i + 1], px[i + 2]) for i in range(0, len(px), 3)]
    p30 = percentile(lum, 0.30)
    fails = []
    if p30 > LIMITS["black_p30_max"]:
        fails.append(f"background not black: 30th percentile brightness {p30} > "
                     f"{LIMITS['black_p30_max']} (navy or grey ground?)")
    return report(fails, {"black_p30": p30})


# ---- loop clip ------------------------------------------------------------------------

def ssim(a, b):
    r = run(["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"])
    m = re.search(r"All:([0-9.]+)", r.stderr.decode(errors="replace"))
    if not m:
        raise RuntimeError(f"ssim failed for {a} / {b}")
    return float(m[1])


def frame_count(path):
    r = run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
             "stream=nb_read_packets,r_frame_rate", "-of", "json", str(path)])
    s = json.loads(r.stdout)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["nb_read_packets"]), float(num) / float(den)


def luma_frames(path, w=64, h=36):
    data = raw(["-i", str(path), "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray"])
    n = w * h
    return [data[i:i + n] for i in range(0, len(data) - n + 1, n)]


def flashes(means, fps):
    """Most flashes (a brightness swing of at least flash_delta and the opposing swing back)
    in any one-second window. Swings are found with hysteresis, so slow drifts don't count."""
    d, swings, state = LIMITS["flash_delta"], [], 0
    peak = trough = means[0]
    for i, v in enumerate(means):
        if state != -1:
            peak = max(peak, v)
        if state != 1:
            trough = min(trough, v)
        if state != -1 and v <= peak - d:
            swings.append(i)
            state, trough = -1, v
        elif state != 1 and v >= trough + d:
            swings.append(i)
            state, peak = 1, v
    win = round(fps)
    return max((sum(1 for s in swings if a <= s < a + win) // 2 for a in range(len(means))), default=0)


def lit_diff(a, b, floor=24):
    """Mean |a - b| / 255 over pixels lit (> floor) in either frame."""
    idx = [i for i in range(len(a)) if a[i] > floor or b[i] > floor]
    return sum(abs(a[i] - b[i]) for i in idx) / len(idx) / 255 if idx else 0.0


def flicker(frames):
    """Mean |p[t] - (p[t-1] + p[t+1]) / 2| over a coarse grid: high for boiling grain and
    strobing, low for smooth motion of any speed."""
    total, count = 0.0, 0
    for a, b, c in zip(frames, frames[1:], frames[2:]):
        total += sum(abs(y - (x + z) / 2) for x, y, z in zip(a, b, c))
        count += len(b)
    return total / count if count else 0.0


def check_clip(path, voice=True):
    n, fps = frame_count(path)
    fails, m = [], {"frames": n, "fps": round(fps, 2)}
    with tempfile.TemporaryDirectory() as tmp:
        shots = {}
        for name, idx in (("first", 0), ("mid", n // 2), ("last", n - 1)):
            shots[name] = Path(tmp) / f"{name}.png"
            ff(["-i", str(path), "-vf", f"select=eq(n\\,{idx})", "-frames:v", "1", "-y", str(shots[name])])
        m["seam_ssim"] = round(ssim(shots["first"], shots["last"]), 3)
        m["motion_ssim"] = round(ssim(shots["first"], shots["mid"]), 3)
        bg = check_image(shots["first"])
        m["black_p30"] = bg["metrics"]["black_p30"]
        fails += bg["fails"]
    frames = luma_frames(path)
    steps = [lit_diff(frames[i], frames[i + 1]) for i in range(0, len(frames) - 1, 4)]
    typical = max(sum(steps) / len(steps), 0.003)
    m["seam_jump"] = round(lit_diff(frames[-1], frames[0]), 4)
    m["seam_step_ratio"] = round(m["seam_jump"] / typical, 2)
    m["motion"] = round(sum(lit_diff(frames[0], f) for f in frames[::4]) / len(frames[::4]), 3)
    if m["seam_step_ratio"] > LIMITS["seam_step_ratio_max"]:
        fails.append(f"loop seam: last->first jump is {m['seam_step_ratio']}x a normal frame step "
                     f"> {LIMITS['seam_step_ratio_max']}")
    if m["motion"] < LIMITS["motion_min"]:
        fails.append(f"too static: motion {m['motion']} < {LIMITS['motion_min']}")
    means = [sum(f) / len(f) for f in frames]
    m["flashes_per_s"] = flashes(means, fps)
    m["flicker"] = round(flicker(frames), 2)
    if m["flashes_per_s"] > LIMITS["flashes_per_s_max"]:
        fails.append(f"flashing: {m['flashes_per_s']} flashes in one second > {LIMITS['flashes_per_s_max']}")
    if m["flicker"] > LIMITS["flicker_max"]:
        fails.append(f"flicker: {m['flicker']} > {LIMITS['flicker_max']}")
    if has_audio(path):  # H3's own audio rides on the clip
        a = check_audio(path, voice=voice, interior_only=False)
        m["audio"] = a["metrics"]
        fails += [f"clip audio: {f}" for f in a["fails"] if not f.startswith("dropout")]
    return report(fails, m)


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", str(path)])
    return bool(r.stdout.strip())


# ---- audio ----------------------------------------------------------------------------

def db(x):
    return 20 * math.log10(x) if x > 0 else -120.0


def check_audio(path, voice=True, interior_only=True):
    pcm = array.array("h", raw(["-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le"]))
    fails, m = [], {"seconds": round(len(pcm) / 8000, 2)}
    if not pcm:
        return report(["no audio decoded"], m)
    # Peak on the full-rate file: resampling to 8 kHz can hide inter-sample overs.
    r = run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"])
    mm = re.search(r"max_volume: (-?[0-9.]+) dB", r.stderr.decode(errors="replace"))
    m["peak_dbfs"] = float(mm[1]) if mm else db(max(abs(v) for v in pcm) / 32768)
    if m["peak_dbfs"] > LIMITS["peak_dbfs_max"]:
        fails.append(f"clipping: peak {m['peak_dbfs']} dBFS > {LIMITS['peak_dbfs_max']}")
    win = 400  # 50 ms
    rms = [db(math.sqrt(sum(v * v for v in pcm[i:i + win]) / win) / 32768)
           for i in range(0, len(pcm) - win + 1, win)]
    if rms:
        med = percentile(rms, 0.5)
        top = max(rms)
        m["median_dbfs"], m["loudest_50ms_dbfs"] = round(med, 1), round(top, 1)
        if top - med > LIMITS["burst_db_max"] and top > LIMITS["burst_floor_dbfs"]:
            fails.append(f"sudden peak: a 50 ms burst {top - med:.1f} dB over the median")
        # Dead air inside the file (the edges may fade).
        inner = rms[20:-20] if interior_only and len(rms) > 60 else rms
        longest = run_len = 0
        for v in inner:
            run_len = run_len + 1 if v < -60 else 0
            longest = max(longest, run_len)
        m["longest_silence_s"] = round(longest * win / 8000, 2)
        if m["longest_silence_s"] > LIMITS["dropout_s_max"]:
            fails.append(f"dropout: {m['longest_silence_s']} s of silence")
    if voice:
        v = voice_words(path)
        m["voice"] = v
        if v.get("words", 0) > LIMITS["voice_words_max"]:
            fails.append(f"voice-like sound: whisper heard {v['text']!r}")
    return report(fails, m)


def voice_words(path):
    if not Path(WHISPER_PYTHON).exists():
        return {"skipped": f"no whisper python at {WHISPER_PYTHON}"}
    r = run([WHISPER_PYTHON, "-I", str(Path(__file__).resolve()), "_whisper", str(path)])
    try:
        return json.loads(r.stdout.decode().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"skipped": f"whisper failed: {r.stderr.decode(errors='replace')[-300:]}"}


def _whisper(path):
    """Runs inside the whisper venv. Counts words whisper is confident about; ASMR noise makes
    it hallucinate short low-confidence phrases ("Thank you."), which are ignored."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "voiceover" / "scripts"))
    from vo_words import decode, load_model
    model = load_model(os.environ.get("QC_WHISPER_MODEL", "base"), "cpu")
    segs, _ = model.transcribe(decode(path), language="en", vad_filter=True, word_timestamps=True)
    words = [w for s in segs if s.no_speech_prob < 0.4 and s.avg_logprob > -0.8
             for w in s.words if w.probability > 0.6]
    print(json.dumps({"words": len(words), "text": " ".join(w.word.strip() for w in words)[:200]}))


# ---- self-test ------------------------------------------------------------------------

def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)

        def make(name, *args):
            out = t / name
            ff(["-y", *args, str(out)])
            return out
        black = make("black.png", "-f", "lavfi", "-i", "color=black:s=320x180,drawbox=x=120:y=60:w=80:h=60:color=orange:t=fill",
                     "-frames:v", "1")
        navy = make("navy.png", "-f", "lavfi", "-i", "color=0x0a0f3c:s=320x180", "-frames:v", "1")
        assert check_image(black)["ok"], check_image(black)
        assert not check_image(navy)["ok"]
        # A loop: a dot circles once and returns; black ground, quiet tone.
        loop = make("loop.mp4", "-f", "lavfi", "-i",
                    "color=black:s=320x180:r=24:d=4,geq=lum='if(lt(hypot(X-160-60*cos(2*PI*T/4),Y-90-60*sin(2*PI*T/4)),20),230,0)':cb=128:cr=128",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=4", "-af", "volume=-20dB",
                    "-shortest", "-pix_fmt", "yuv420p")
        r = check_clip(loop, voice=False)
        assert r["ok"], r
        static = make("static.mp4", "-f", "lavfi", "-i", "color=black:s=320x180:r=24:d=4,drawbox=x=150:y=80:w=20:h=20:color=white:t=fill",
                      "-pix_fmt", "yuv420p")
        assert any("too static" in f for f in check_clip(static, voice=False)["fails"])
        # Same circling dot, but it stops halfway round: the loop can't close.
        jump = make("jump.mp4", "-f", "lavfi", "-i",
                    "color=black:s=320x180:r=24:d=4,geq=lum='if(lt(hypot(X-160-60*cos(PI*T/4),Y-90-60*sin(PI*T/4)),20),230,0)':cb=128:cr=128",
                    "-pix_fmt", "yuv420p")
        assert any("loop seam" in f for f in check_clip(jump, voice=False)["fails"])
        strobe = make("strobe.mp4", "-f", "lavfi", "-i", "color=black:s=320x180:r=24:d=4,geq=lum='if(lt(mod(N,6),3),230,0)':cb=128:cr=128",
                      "-pix_fmt", "yuv420p")
        assert any("flashing" in f for f in check_clip(strobe, voice=False)["fails"])
        tone = make("tone.wav", "-f", "lavfi", "-i", "anoisesrc=d=6:a=0.05:c=pink")
        assert check_audio(tone, voice=False)["ok"], check_audio(tone, voice=False)
        hot = make("hot.wav", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-af", "volume=24dB")
        assert any("clipping" in f for f in check_audio(hot, voice=False)["fails"])
        pop = make("pop.wav", "-f", "lavfi", "-i",
                   "aevalsrc='if(between(t,2,2.05),0.9*sin(2*PI*80*t),0.01*sin(2*PI*300*t))':d=4:s=8000")
        assert any("sudden peak" in f for f in check_audio(pop, voice=False)["fails"])
        gap = make("gap.wav", "-f", "lavfi", "-i",
                   "aevalsrc='if(between(t,3,5),0,0.05*sin(2*PI*300*t))':d=8:s=8000")
        assert any("dropout" in f for f in check_audio(gap, voice=False)["fails"])
    print("self-test passed")


def main():
    if sys.argv[1:2] == ["--self-test"]:
        self_test()
        return
    if sys.argv[1:2] == ["_whisper"]:
        _whisper(sys.argv[2])
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("kind", choices=["image", "clip", "audio"])
    p.add_argument("path")
    p.add_argument("--no-voice", action="store_true")
    a = p.parse_args()
    r = (check_image(a.path) if a.kind == "image"
         else check_clip(a.path, not a.no_voice) if a.kind == "clip"
         else check_audio(a.path, not a.no_voice))
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
