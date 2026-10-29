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

render: reads media/mix.json if present (per-segment volume and EQ for the segment, clip and
bed layers; see mix_sheet), reads script/script.md (## = movement, VO: Snn ... = segment), joins Spliced/Snn.mp4
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


# Named EQ moves, so a mix note can say "crisp" instead of a frequency.
EQ_PRESETS = {
    "crisp": [{"freq": 4500, "gain": 4, "q": 0.8}],      # crunch, crackle, splash detail
    "soften": [{"freq": 6500, "gain": -4, "q": 0.9}],    # tame hiss and harsh highs
    "warm": [{"freq": 250, "gain": 3, "q": 0.8}],        # body, softness
    "clean-low": [{"highpass": 60}],                     # rumble, handling thumps
}
LAYERS = ("segment", "clip", "bed")


def eq_filters(eq):
    """ffmpeg filters for a list of presets and/or {freq, gain, q} / {highpass} / {lowpass}."""
    out = []
    for e in eq:
        for band in EQ_PRESETS[e] if isinstance(e, str) else [e]:
            if "highpass" in band:
                out.append(f"highpass=f={float(band['highpass'])}")
            elif "lowpass" in band:
                out.append(f"lowpass=f={float(band['lowpass'])}")
            else:
                out.append(f"equalizer=f={float(band['freq'])}:t=q:w={float(band.get('q', 1))}"
                           f":g={float(band['gain'])}")
    return out


def mix_sheet(project, ids):
    """media/mix.json: {"*" | "Snn": {"segment" | "clip" | "bed": {"db": n, "eq": [...]}}}.
    "*" applies to every segment; a segment's own entry adds to it (dB add, EQ appends).
    Typos are errors, not silent no-ops: the creator should hear what they wrote."""
    f = Path(project) / "media" / "mix.json"
    sheet = json.loads(f.read_text("utf-8-sig")) if f.exists() else {}
    for key, layers in sheet.items():
        if key != "*" and key not in ids:
            raise SystemExit(f"mix.json: unknown segment {key!r} (segments: {', '.join(ids)})")
        for layer, v in layers.items():
            if layer not in LAYERS:
                raise SystemExit(f"mix.json {key}: unknown layer {layer!r} (use {', '.join(LAYERS)})")
            if set(v) - {"db", "eq"}:
                raise SystemExit(f"mix.json {key}.{layer}: only 'db' and 'eq' are allowed")
            for e in v.get("eq", []):
                if isinstance(e, str) and e not in EQ_PRESETS:
                    raise SystemExit(f"mix.json {key}.{layer}: unknown EQ preset {e!r} "
                                     f"(presets: {', '.join(EQ_PRESETS)})")
                if isinstance(e, dict) and not ({"highpass"} <= set(e) or {"lowpass"} <= set(e)
                                                or {"freq", "gain"} <= set(e)):
                    raise SystemExit(f"mix.json {key}.{layer}: EQ band needs freq+gain, highpass or lowpass")
    result = {}
    for sid in ids:
        result[sid] = {}
        for layer in LAYERS:
            parts = [sheet.get("*", {}).get(layer, {}), sheet.get(sid, {}).get(layer, {})]
            result[sid][layer] = {"db": sum(float(x.get("db", 0)) for x in parts),
                                  "eq": [e for x in parts for e in x.get("eq", [])]}
    return result


def layer_chain(base_db, layer):
    """The layer's EQ filters, then its volume (channel level + mix.json dB)."""
    return ",".join([*eq_filters(layer["eq"]), f"volume={base_db + layer['db']}dB"])


def render(project, out):
    p, s = Path(project), style(project)
    segs = session(project)
    if not segs:
        raise SystemExit("script/script.md has no 'VO: Snn' segment lines")
    mixes = mix_sheet(project, [sid for sid, _ in segs])
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
            mx = mixes[sid]
            mix = (f"[0:a]{layer_chain(s['sfx_db'], mx['clip'])}[c];"
                   f"[1:a]aresample=48000,{layer_chain(s['voice_db'], mx['segment'])}[g];")
            if mv in beds:
                ins += ["-ss", f"{off:.3f}", "-t", f"{ln:.3f}", "-i", str(beds[mv])]
                mix += (f"[2:a]{layer_chain(s['music_db'], mx['bed'])}[b];"
                        "[c][g][b]amix=inputs=3:duration=first:normalize=0[a]")
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
                 f"[aj]afade=t=out:st={total - fade:.3f}:d={fade}[a]")
        # Two-pass loudness: encode the picture once with the mix as PCM, measure the mix, then
        # copy the picture and normalise the sound linearly to the measured values, so the
        # target and true peak land on the first render.
        joined = Path(tmp) / "joined.mkv"
        ffmpeg([*[a for m in mixed for a in ("-i", str(m))], "-filter_complex", graph,
                "-map", "[v]", "-map", "[a]", *ENCODE[:8], "-c:a", "pcm_s24le", str(joined)])
        target = f"I={s['loudness_lufs']}:TP={s['true_peak_db']}:LRA={s['lra_max']}"
        m = loudnorm_json(["-i", str(joined), "-af", f"loudnorm={target}:print_format=json",
                           "-f", "null", "-"])
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        done = loudnorm_json(["-i", str(joined), "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af",
                              f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                              f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                              f":offset={m['target_offset']}:linear=true:print_format=json,aresample=48000",
                              *ENCODE[8:], "-y", str(out)])
    return {"out": str(out), "seconds": round(seconds(out), 2), "segments": len(segs),
            "beds": sorted(f"M{m:02d}" for m in beds),
            "mix": {sid: m for sid, m in mixes.items()
                    if any(v["db"] or v["eq"] for v in m.values())},
            "expected_seconds": round(total, 2), "style": s,
            "loudness": {"lufs": float(done["output_i"]), "true_peak_db": float(done["output_tp"]),
                         "lra": float(done["output_lra"]),
                         "mode": done.get("normalization_type", "")}}


def loudnorm_json(args):
    """Run ffmpeg with a loudnorm print_format=json filter and return its measurement."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True,
                       check=False)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed: {r.stderr.strip()[-2000:]}")
    return json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])


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
        mx = mix_sheet(t, ["S01", "S02", "S03"])  # no mix.json: all flat
        assert mx["S02"]["segment"] == {"db": 0, "eq": []}
        (t / "media").mkdir()
        (t / "media" / "mix.json").write_text(json.dumps(
            {"*": {"bed": {"db": -2}}, "S02": {"segment": {"db": 3, "eq": ["crisp", {"highpass": 60}]},
                                               "bed": {"db": -1}}}), "utf-8")
        mx = mix_sheet(t, ["S01", "S02", "S03"])
        assert mx["S02"]["bed"]["db"] == -3 and mx["S01"]["bed"]["db"] == -2
        assert eq_filters(mx["S02"]["segment"]["eq"]) == ["equalizer=f=4500.0:t=q:w=0.8:g=4.0", "highpass=f=60.0"]
        for bad in ({"S09": {}}, {"S01": {"crunch": {}}}, {"S01": {"bed": {"eq": ["sparkly"]}}}):
            (t / "media" / "mix.json").write_text(json.dumps(bad), "utf-8")
            try:
                mix_sheet(t, ["S01"])
                raise AssertionError(f"accepted {bad}")
            except SystemExit:
                pass
        (t / "media" / "mix.json").write_text(json.dumps(
            {"S02": {"segment": {"db": 3, "eq": ["crisp"]}, "clip": {"eq": ["soften"]}}}), "utf-8")
        r = render(t, t / "out.mp4")
        assert r["mix"] == {"S02": {"segment": {"db": 3.0, "eq": ["crisp"]}, "clip": {"db": 0, "eq": ["soften"]},
                                    "bed": {"db": 0, "eq": []}}}, r["mix"]
        # 10 + 7 + 9 - 2 (segment join) - 4 (movement join) = 20
        assert abs(r["expected_seconds"] - 20) < 0.1 and abs(r["seconds"] - r["expected_seconds"]) < 0.2, r
        assert r["beds"] == ["M01"], r
        # Lands on the channel's loudness defaults first time (-18 LUFS, -2 dBTP).
        assert abs(r["loudness"]["lufs"] + 18) <= 1 and r["loudness"]["true_peak_db"] <= -1.5, r["loudness"]
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
