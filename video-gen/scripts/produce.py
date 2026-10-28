# SPDX-License-Identifier: MIT OR Apache-2.0
"""Make a whole generated-video session in one command: audio, beds, reference images, loop
clips, splices and the final render, from one spec file.

Usage:
  python produce.py --project P [--until first-clips|clips|render] [--retries 2] [--dry-run]
  python produce.py --self-test

Reads script/script.md (## = movement, VO: Snn = segment) and media/produce.json:

  {"name": "asmr-002", "clips": 4, "seconds": 8,
   "segments": {"S01": {"audio": {"prompt": "TrackType: SFX, ...", "chunks": 2, "seconds": 120},
                        "ref": "<MOSS prompt>", "clip": "<H3 prompt>", "clips": 4, "seed": 7}},
   "beds": {"M01": {"prompt": "TrackType: SFX, soft steady rain ...", "seconds": 150}}}

Order: segment audio (chunks crossfaded into Segments/Snn.wav) and beds, then each segment's
first clip and one contact sheet of them all (cache/first-clips.png), then the remaining clips,
splices and exports/<name>.mp4. Every step keeps finished files, so a rerun resumes; stop
after a phase with --until. Each generated file goes through qc.py with seed re-rolls. A job
that fails all its retries is reported and blocks only the steps that need it.

Prints a short summary and writes media/produce-report.json with every job's seed, QC
attempts and errors, the render's loudness, and the time each phase took. ComfyUI must be
running. Linking the files in Spear Fia (for a FilmCraft push) is not done here.
"""

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "audio-gen" / "scripts"))
import comfy_audio  # noqa: E402
import comfy_video  # noqa: E402
import splice  # noqa: E402

FOLDERS = {"Segments": "voiceover", "Spliced": "b-roll", "Beds": "music"}
CHUNK_XFADE = 3.0
UNTIL = ("first-clips", "clips", "render")


def load_spec(project):
    """The spec, checked against the session sheet: every segment line has an entry, every
    entry has a line, beds name real movements."""
    p = Path(project)
    f = p / "media" / "produce.json"
    if not f.exists():
        raise SystemExit(f"no {f}: write the spec first (format in `produce.py --help`)")
    spec = json.loads(f.read_text("utf-8-sig"))
    session = splice.session(project)
    ids = [sid for sid, _ in session]
    movements = sorted({mv for _, mv in session})
    segs = spec.get("segments", {})
    problems = [f"segment {sid} is in script.md but not in produce.json" for sid in ids if sid not in segs]
    problems += [f"segment {sid} is in produce.json but not in script.md" for sid in segs if sid not in ids]
    for sid, s in segs.items():
        problems += [f"{sid}: missing {k!r}" for k in ("audio", "ref", "clip") if k not in s]
        if "audio" in s and "prompt" not in s["audio"]:
            problems.append(f"{sid}: audio needs a prompt")
    problems += [f"bed {m} names no movement (movements: {movements})" for m in spec.get("beds", {})
                 if not (m[:1] == "M" and m[1:].isdigit() and int(m[1:]) in movements)]
    if problems:
        raise SystemExit("produce.json:\n  " + "\n  ".join(problems))
    return spec, ids


def base_seed(name, sid, spec_seed=None):
    """A stable seed per segment, so a rerun asks for the same takes."""
    if spec_seed is not None:
        return int(spec_seed)
    return int(hashlib.sha256(f"{name}/{sid}".encode()).hexdigest()[:7], 16)


def plan(project, spec, ids):
    """Every file to make, in order, as (phase, kind, out, job)."""
    p = Path(project)
    name = spec.get("name") or p.name
    steps = []
    for sid in ids:
        s = spec["segments"][sid]
        a, seed = s["audio"], base_seed(name, sid, s.get("seed"))
        for k in range(1, int(a.get("chunks", 2)) + 1):
            steps.append(("audio", "audio", p / "cache" / "audio" / f"{sid}_{k}.wav",
                          {"prompt": a["prompt"], "seconds": float(a.get("seconds", 120)),
                           "seed": seed + k * 7919}))
    for m, b in spec.get("beds", {}).items():
        steps.append(("audio", "audio", p / "Beds" / f"{m}.wav",
                      {"prompt": b["prompt"], "seconds": float(b.get("seconds", 150)),
                       "seed": base_seed(name, m, b.get("seed"))}))
    for phase, ks in (("first-clips", lambda n: [1]), ("clips", lambda n: range(2, n + 1))):
        for sid in ids:
            s = spec["segments"][sid]
            seed = base_seed(name, sid, s.get("seed"))
            for k in ks(int(s.get("clips", spec.get("clips", 4)))):
                steps.append((phase, "clip", p / "Clips" / sid / f"{sid}_{k}.mp4",
                              {"prompt": s["clip"], "ref_prompt": s["ref"], "image": str(p / "Refs" / f"{sid}.png"),
                               "seconds": float(s.get("seconds", spec.get("seconds", 8))),
                               "seed": seed + k * 104729}))
    return steps


def ensure_folders(project):
    """Media folders and their roles in project.json (written as plain UTF-8: a BOM stops the
    desktop opening the project)."""
    p = Path(project)
    for d in [*FOLDERS, "Refs", "Clips", "cache/audio", "exports"]:
        (p / d).mkdir(parents=True, exist_ok=True)
    f = p / "project.json"
    proj = json.loads(f.read_text("utf-8-sig"))
    have = {m["path"] for m in proj.get("media_folders", [])}
    missing = [{"path": d, "role": r} for d, r in FOLDERS.items() if d not in have]
    if missing:
        proj.setdefault("media_folders", []).extend(missing)
        f.write_text(json.dumps(proj, indent=2, ensure_ascii=False) + "\n", "utf-8", newline="\n")


def join_chunks(chunks, out, xfade=CHUNK_XFADE):
    """Equal-power crossfade the chunks, in order, into one WAV."""
    ins = [a for c in chunks for a in ("-i", str(c))]
    if len(chunks) == 1:
        graph = "[0:a]anull[a]"
    else:
        graph, prev = [], "[0:a]"
        for k in range(1, len(chunks)):
            nxt = "[a]" if k == len(chunks) - 1 else f"[j{k}]"
            graph.append(f"{prev}[{k}:a]acrossfade=d={xfade}:c1=qsin:c2=qsin{nxt}")
            prev = nxt
        graph = ";".join(graph)
    out.parent.mkdir(parents=True, exist_ok=True)
    splice.ffmpeg([*ins, "-filter_complex", graph, "-map", "[a]", "-ar", "48000", "-c:a", "pcm_s24le", str(out)])


def newer(out, sources):
    return out.exists() and all(out.stat().st_mtime >= Path(s).stat().st_mtime for s in sources)


def contact_sheet(clips, out):
    """One tile row per clip (4 frames, 480 px), stacked into one image."""
    with tempfile.TemporaryDirectory() as tmp:
        rows = []
        for i, c in enumerate(clips):
            row = Path(tmp) / f"{i}.png"
            splice.ffmpeg(["-i", str(c), "-vf", "fps=0.5,scale=480:-2,tile=4x1", "-frames:v", "1", str(row)])
            rows.append(row)
        graph = "".join(f"[{i}:v]" for i in range(len(rows))) + (f"vstack=inputs={len(rows)}" if len(rows) > 1 else "null")
        splice.ffmpeg([*[a for r in rows for a in ("-i", str(r))], "-filter_complex", graph, "-frames:v", "1", str(out)])


def run(project, until="render", retries=2, dry_run=False):
    p = Path(project)
    spec, ids = load_spec(project)
    steps = plan(project, spec, ids)
    todo = [s for s in steps if not s[2].exists()]
    if dry_run:
        print(json.dumps({"segments": ids, "files": len(steps), "to_make": len(todo),
                          "by_phase": {ph: sum(1 for s in todo if s[0] == ph) for ph in ("audio", *UNTIL[:2])}}))
        return 0
    ensure_folders(project)
    comfy_video.call("/system_stats")
    report = {"jobs": [], "errors": [], "phases": {}}
    stop_at = UNTIL.index(until)

    def make(phase):
        started = time.time()
        for ph, kind, out, job in steps:
            if ph != phase or out.exists():
                continue
            entry = {"out": str(out.relative_to(p)), "seed": job["seed"]}
            try:
                if kind == "audio":
                    out.parent.mkdir(parents=True, exist_ok=True)
                    _, seed, attempts = comfy_audio.generate_checked({**job, "out": str(out)}, 8, retries)
                    entry.update(seed=seed, attempts=[a["fails"] for a in attempts])
                else:
                    _, seed, secs, rec = comfy_video.generate({**job, "out": str(out)}, retries, True)
                    entry.update(seed=seed, attempts=[a["fails"] for a in rec["attempts"]],
                                 ref_attempts=[a["fails"] for a in rec.get("ref_attempts", [])])
            except (RuntimeError, OSError) as e:
                entry["error"] = str(e)
                report["errors"].append(entry)
            report["jobs"].append(entry)
            print(f"{phase} {entry['out']}: " + ("FAILED " + entry["error"] if "error" in entry
                                                else f"ok after {len(entry['attempts'])} take(s)"), flush=True)
        report["phases"][phase] = round(time.time() - started)

    def finish(code):
        (p / "media").mkdir(exist_ok=True)
        (p / "media" / "produce-report.json").write_text(json.dumps(report, indent=1), "utf-8")
        made = len(report["jobs"])
        rerolls = sum(len(j.get("attempts", [])) - 1 for j in report["jobs"] if "attempts" in j)
        print(f"made {made} files, {rerolls} QC re-rolls, {len(report['errors'])} failed; "
              f"phases {report['phases']}; report media/produce-report.json")
        for k in ("sheet", "render"):
            if k in report:
                print(f"{k}: {json.dumps(report[k]) if isinstance(report[k], dict) else report[k]}")
        return code

    make("audio")
    for sid in ids:  # crossfade each segment's chunks
        a = spec["segments"][sid]["audio"]
        chunks = [p / "cache" / "audio" / f"{sid}_{k}.wav" for k in range(1, int(a.get("chunks", 2)) + 1)]
        out = p / "Segments" / f"{sid}.wav"
        if all(c.exists() for c in chunks) and not newer(out, chunks):
            join_chunks(chunks, out)
    make("first-clips")
    firsts = [p / "Clips" / sid / f"{sid}_1.mp4" for sid in ids]
    sheet = p / "cache" / "first-clips.png"
    if all(c.exists() for c in firsts) and not newer(sheet, firsts):
        contact_sheet(firsts, sheet)
    if sheet.exists():
        report["sheet"] = str(sheet)
    if stop_at == 0:
        return finish(1 if report["errors"] else 0)
    make("clips")
    if stop_at == 1 or report["errors"]:
        return finish(1 if report["errors"] else 0)
    started = time.time()
    for sid in ids:
        clips = sorted((p / "Clips" / sid).glob(f"{sid}_*.mp4"))
        clips = [c for c in clips if ".rejected-" not in c.name]
        audio, out = p / "Segments" / f"{sid}.wav", p / "Spliced" / f"{sid}.mp4"
        if not newer(out, [*clips, audio]):
            # splice.segment reads every clip in a folder, so give it only the accepted ones.
            with tempfile.TemporaryDirectory() as tmp:
                for c in clips:
                    (Path(tmp) / c.name).write_bytes(c.read_bytes())
                splice.segment(tmp, audio, out, splice.style(project)["clip_crossfade_seconds"],
                               base_seed(spec.get("name") or p.name, sid))
    name = spec.get("name") or p.name
    r = splice.render(project, p / "exports" / f"{name}.mp4")
    report["render"] = {"out": r["out"], "seconds": r["seconds"], "loudness": r["loudness"]}
    report["phases"]["splice+render"] = round(time.time() - started)
    return finish(0)


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "script").mkdir()
        (t / "media").mkdir()
        (t / "script" / "script.md").write_text("## 1 · A\n\nVO: S01 a\nVO: S02 b\n\n## 2 · B\n\nVO: S03 c\n", "utf-8")
        (t / "project.json").write_text('{"media_folders": [{"path": "Music", "role": "music"}]}', "utf-8")
        seg = {"audio": {"prompt": "x", "chunks": 2, "seconds": 90}, "ref": "r", "clip": "c"}
        spec = {"name": "t", "clips": 3, "segments": {"S01": seg, "S02": {**seg, "clips": 2}, "S03": seg},
                "beds": {"M01": {"prompt": "rain"}, "M02": {"prompt": "pad"}}}
        (t / "media" / "produce.json").write_text(json.dumps(spec), "utf-8")
        s, ids = load_spec(t)
        steps = plan(t, s, ids)
        count = lambda ph: sum(1 for x in steps if x[0] == ph)  # noqa: E731
        assert (count("audio"), count("first-clips"), count("clips")) == (8, 3, 5), steps
        seeds = [x[3]["seed"] for x in steps]
        assert len(seeds) == len(set(seeds)), "seeds must differ"
        assert plan(t, s, ids)[0][3]["seed"] == steps[0][3]["seed"], "seeds must be stable"
        ensure_folders(t)
        roles = {m["path"]: m["role"] for m in json.loads((t / "project.json").read_text("utf-8"))["media_folders"]}
        assert roles == {"Music": "music", "Segments": "voiceover", "Spliced": "b-roll", "Beds": "music"}
        assert not (t / "project.json").read_bytes().startswith(b"\xef\xbb\xbf")
        for bad in ({**spec, "segments": {"S01": seg, "S02": seg}},
                    {**spec, "beds": {"M07": {"prompt": "x"}}},
                    {**spec, "segments": {**spec["segments"], "S03": {"ref": "r", "clip": "c"}}}):
            (t / "media" / "produce.json").write_text(json.dumps(bad), "utf-8")
            try:
                load_spec(t)
                raise AssertionError(f"accepted {bad}")
            except SystemExit:
                pass
        chunks = []
        for k, hz in enumerate((300, 500)):
            c = t / f"c{k}.wav"
            splice.ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={hz}:duration=10", str(c)])
            chunks.append(c)
        join_chunks(chunks, t / "Segments" / "S01.wav")
        assert abs(splice.seconds(t / "Segments" / "S01.wav") - (20 - CHUNK_XFADE)) < 0.1
        for k in range(2):
            splice.ffmpeg(["-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=4", "-pix_fmt", "yuv420p",
                           str(t / f"v{k}.mp4")])
        contact_sheet([t / "v0.mp4", t / "v1.mp4"], t / "sheet.png")
        assert (t / "sheet.png").stat().st_size > 0
    print("self-test passed")


def main():
    if sys.argv[1:2] == ["--self-test"]:
        self_test()
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--until", choices=UNTIL, default="render")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true", help="count what would be made, generate nothing")
    a = ap.parse_args()
    sys.exit(run(a.project, a.until, a.retries, a.dry_run))


if __name__ == "__main__":
    main()
