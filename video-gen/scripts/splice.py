# SPDX-License-Identifier: MIT OR Apache-2.0
"""Splice loop clips into segment videos, then render a whole session with ffmpeg.

Usage:
  python splice.py segment --clips Clips/S01 --audio Segments/S01.wav --out Spliced/S01.mp4
                           [--xfade 0.75] [--seed N]
  python splice.py render --project <folder> --out exports/<name>.mp4
  python splice.py --self-test

segment: plays the clips in shuffled order (never the same clip twice in a row), crossfaded,
repeating until the picture is exactly as long as the segment audio. Keeps the clips' own
audio; the segment audio itself is mixed in by render.

render: reads script/script.md (## = movement, VO: Snn ... = segment), joins Spliced/Snn.mp4
with Segments/Snn.wav in order, dips the picture to black between segments and movements
(audio crossfades), loops each movement's ambient bed Beds/Mnn.wav under it if present, mixes
and normalises loudness. Levels and fades come from the spearfia-style block in the project's channel.md
(execution.md), with the channel's proposed values as defaults. Needs ffmpeg and ffprobe.
"""

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULTS = {"voice_db": 0, "sfx_db": -8, "music_db": -24, "loudness_lufs": -18, "true_peak_db": -2, "lra_max": 7,
            "clip_crossfade_seconds": 0.75, "segment_crossfade_seconds": 2,
            "movement_crossfade_seconds": 4, "final_fade_seconds": 30}
ENCODE = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "320k", "-ar", "48000"]


def seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "csv=p=0", str(path)], capture_output=True, text=True, check=False)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise SystemExit(f"ffprobe couldn't read {path}") from None


def ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True,
                       check=False)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed: {r.stderr.strip()[-2000:]}")


def order(lengths, target, x, rng):
    """Clip indices, shuffled and never repeating back to back, until the crossfaded run
    covers `target` seconds."""
    seq, total, bag = [], 0.0, []
    while total < target:
        if not bag:
            bag = list(range(len(lengths)))
            rng.shuffle(bag)
            if seq and len(bag) > 1 and bag[0] == seq[-1]:
                bag.append(bag.pop(0))
        i = bag.pop(0)
        total += lengths[i] - (x if seq else 0)
        seq.append(i)
    return seq


def chain(inputs, lengths, xs, transition="fade"):
    """filter_complex that joins inputs (video [n:v], audio [n:a]) with an xfade `transition`
    of xs[k] seconds between input k and k+1; audio crossfades. Output labels [v] and [a]."""
    if len(inputs) == 1:
        return "[0:v]null[v];[0:a]anull[a]"
    parts, v, a, run = [], "[0:v]", "[0:a]", lengths[0]
    for k in range(1, len(inputs)):
        x = xs[k - 1]
        last = k == len(inputs) - 1
        vo, ao = ("[v]", "[a]") if last else (f"[v{k}]", f"[a{k}]")
        parts.append(f"{v}[{k}:v]xfade=transition={transition}:duration={x}:offset={run - x:.3f}{vo}")
        parts.append(f"{a}[{k}:a]acrossfade=d={x}{ao}")
        v, a, run = vo, ao, run + lengths[k] - x
    return ";".join(parts)


def segment(clips_dir, audio, out, x, seed):
    clips = sorted(p for p in Path(clips_dir).iterdir() if p.suffix.lower() in (".mp4", ".mov", ".webm"))
    if not clips:
        raise SystemExit(f"no clips in {clips_dir}")
    lengths = [seconds(c) for c in clips]
    if min(lengths) <= 2 * x:
        raise SystemExit(f"clips must be longer than twice the crossfade ({2 * x} s)")
    target = seconds(audio)
    seq = order(lengths, target, x, random.Random(seed))
    args = [a for i in seq for a in ("-i", str(clips[i]))]
    graph = chain(seq, [lengths[i] for i in seq], [x] * (len(seq) - 1))
    # Clips are normalised to one size/rate first so xfade accepts them.
    norm = ";".join(f"[{k}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
                    f"pad=1920:1080:-1:-1,fps=24,format=yuv420p,setsar=1[n{k}];"
                    f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo[m{k}]"
                    for k in range(len(seq)))
    graph = norm + ";" + re.sub(r"\[(\d+):([va])\]",
                                lambda m: f"[{'n' if m[2] == 'v' else 'm'}{m[1]}]", graph)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg([*args, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{target:.3f}",
            *ENCODE, str(out)])
    return {"out": str(out), "seconds": round(seconds(out), 2), "audio_seconds": round(target, 2),
            "clips": [clips[i].name for i in seq]}


def session(project):
    """[(segment id, movement index)] in script order."""
    text = (Path(project) / "script" / "script.md").read_text("utf-8")
    segs, movement = [], 0
    for line in text.splitlines():
        if line.startswith("## "):
            movement += 1
        elif m := re.match(r"\s*VO:\s*(S\d+)\b", line, re.I):
            segs.append((m[1].upper(), movement))
    return segs


def style(project):
    s = dict(DEFAULTS)
    brief = Path(project) / "channel.md"
    if brief.exists() and (m := re.search(r"```spearfia-style\n(.*?)```", brief.read_text("utf-8"), re.S)):
        block = json.loads(m[1])
        s.update({k: v for k, v in block.get("mix", {}).items() if k in s})
        s.update({k: v for k, v in block.get("render", {}).items() if k in s})
    return s


def render(project, out):
    p, s = Path(project), style(project)
    segs = session(project)
    if not segs:
        raise SystemExit("script/script.md has no 'VO: Snn' segment lines")
    missing = [f for sid, _ in segs for f in (p / "Spliced" / f"{sid}.mp4", p / "Segments" / f"{sid}.wav")
               if not f.exists()]
    if missing:
        raise SystemExit("missing: " + ", ".join(map(str, missing)))
    lengths = [seconds(p / "Spliced" / f"{sid}.mp4") for sid, _ in segs]
    xs = [s["movement_crossfade_seconds"] if segs[k][1] != segs[k + 1][1]
          else s["segment_crossfade_seconds"] for k in range(len(segs) - 1)]
    # Where each segment starts on its movement's timeline, so the bed runs on unbroken
    # through segment joins (both sides of a crossfade read the bed at the same moment).
    offsets, run = [], 0.0
    for k, (sid, mv) in enumerate(segs):
        run = 0.0 if k == 0 or segs[k - 1][1] != mv else run + lengths[k - 1] - xs[k - 1]
        offsets.append(run)
    with tempfile.TemporaryDirectory() as tmp:
        beds = {}
        for mv in dict.fromkeys(m for _, m in segs):
            src = p / "Beds" / f"M{mv:02d}.wav"
            if src.exists():
                span = max(o + l for o, l, (_, m) in zip(offsets, lengths, segs) if m == mv)
                beds[mv] = Path(tmp) / f"M{mv:02d}.wav"
                ffmpeg(["-stream_loop", "-1", "-i", str(src), "-t", f"{span + 1:.3f}",
                        "-ar", "48000", "-ac", "2", str(beds[mv])])
        mixed = []
        for (sid, mv), off, ln in zip(segs, offsets, lengths):
            # picture + clip audio at sfx_db + segment audio at voice_db (+ bed at music_db)
            m = Path(tmp) / f"{sid}.mkv"
            ins = ["-i", str(p / "Spliced" / f"{sid}.mp4"), "-i", str(p / "Segments" / f"{sid}.wav")]
            mix = (f"[0:a]volume={s['sfx_db']}dB[c];[1:a]aresample=48000,volume={s['voice_db']}dB[g];")
            if mv in beds:
                ins += ["-ss", f"{off:.3f}", "-t", f"{ln:.3f}", "-i", str(beds[mv])]
                mix += f"[2:a]volume={s['music_db']}dB[b];[c][g][b]amix=inputs=3:duration=first:normalize=0[a]"
            else:
                mix += "[c][g]amix=inputs=2:duration=first:normalize=0[a]"
            ffmpeg([*ins, "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "pcm_s16le", str(m)])
            mixed.append(m)
        lengths = [seconds(m) for m in mixed]
        total = sum(lengths) - sum(xs)
        fade = min(s["final_fade_seconds"], total / 2)
        graph = (chain(mixed, lengths, xs, "fadeblack").replace("[v]", "[vj]").replace("[a]", "[aj]") +
                 f";[vj]fade=t=out:st={total - fade:.3f}:d={fade}[v];"
                 f"[aj]afade=t=out:st={total - fade:.3f}:d={fade},"
                 f"loudnorm=I={s['loudness_lufs']}:TP={s['true_peak_db']}:LRA={s['lra_max']},"
                 "aresample=48000[a]")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        ffmpeg([*[a for m in mixed for a in ("-i", str(m))], "-filter_complex", graph,
                "-map", "[v]", "-map", "[a]", *ENCODE, str(out)])
    return {"out": str(out), "seconds": round(seconds(out), 2), "segments": len(segs),
            "beds": sorted(f"M{m:02d}" for m in beds),
            "expected_seconds": round(total, 2), "style": s}


def self_test():
    rng = random.Random(1)
    seq = order([8, 8, 8], 60, 0.75, rng)
    assert all(a != b for a, b in zip(seq, seq[1:])), seq
    assert 8 * len(seq) - 0.75 * (len(seq) - 1) >= 60
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "Clips").mkdir()
        for i, hz in enumerate((300, 400, 500)):
            ffmpeg(["-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=4",
                    "-f", "lavfi", "-i", f"sine=frequency={hz}:duration=4", "-shortest",
                    *ENCODE, str(t / "Clips" / f"c{i}.mp4")])
        (t / "Segments").mkdir()
        for sid, d in (("S01", 10), ("S02", 7), ("S03", 9)):
            ffmpeg(["-f", "lavfi", "-i", f"anoisesrc=d={d}:a=0.05", "-ar", "48000", "-ac", "2",
                    str(t / "Segments" / f"{sid}.wav")])
            r = segment(t / "Clips", t / "Segments" / f"{sid}.wav", t / "Spliced" / f"{sid}.mp4", 0.75, 1)
            assert abs(r["seconds"] - d) < 0.15, r
        (t / "Beds").mkdir()
        ffmpeg(["-f", "lavfi", "-i", "sine=frequency=110:duration=5", "-ar", "48000", "-ac", "2",
                str(t / "Beds" / "M01.wav")])  # shorter than movement 1, so it must loop
        (t / "script").mkdir()
        (t / "script" / "script.md").write_text("## 1 · A\n\nVO: S01 a\n\nVO: S02 b\n\n## 2 · B\n\nVO: S03 c\n",
                                                "utf-8")
        r = render(t, t / "out.mp4")
        # 10 + 7 + 9 - 2 (segment join) - 4 (movement join) = 20
        assert abs(r["expected_seconds"] - 20) < 0.1 and abs(r["seconds"] - r["expected_seconds"]) < 0.2, r
        assert r["beds"] == ["M01"], r
        # mid-transition frame (segment join at about 9 s) is near black
        ffmpeg(["-ss", "9.0", "-i", str(t / "out.mp4"), "-frames:v", "1", "-vf", "scale=1:1",
                "-f", "rawvideo", "-pix_fmt", "gray", str(t / "px.raw")])
        assert (t / "px.raw").read_bytes()[0] < 40, (t / "px.raw").read_bytes()
    print("self-test passed")


def main():
    if sys.argv[1:2] == ["--self-test"]:
        self_test()
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("segment")
    a.add_argument("--clips", required=True)
    a.add_argument("--audio", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--xfade", type=float, default=DEFAULTS["clip_crossfade_seconds"])
    a.add_argument("--seed", type=int)
    b = sub.add_parser("render")
    b.add_argument("--project", required=True)
    b.add_argument("--out", required=True)
    a = p.parse_args()
    r = (segment(a.clips, a.audio, a.out, a.xfade, a.seed) if a.cmd == "segment"
         else render(a.project, a.out))
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
