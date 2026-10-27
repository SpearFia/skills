# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fill a pool of broad Visual Script cues from one long source video, in two calls.

Usage:
  python pool.py cut --project P --pool R5 --cues ID,ID,... (--url URL | --file PATH)
                 [--library D:/SpearFia/library] [--len 5] [--skip-head 60] [--skip-tail 120]
      Downloads the source once (cache in P/media/cache), cuts clips spread across it
      (one per ~5 s of each cue's narration, skipping ranges already used from this
      source), runs qc.py, writes 4x4 contact sheets and P/media/pool-batches/<batch>.json.
      Prints a short summary: sheet paths and clip numbers with automatic flags.
  python pool.py commit --project P --batch NAME [--drop 3,7] [--keep-cache]
      Deletes dropped clips, appends kept clips to media/manifest.jsonl and library.jsonl,
      deletes the cached source (unless --keep-cache) and prints the links_add payload.
  python pool.py --self-test

For pool cues (match subject/mood) only. Exact cues still get their own search.
Needs yt-dlp (for --url), ffmpeg and ffprobe. Standard library only.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qc  # noqa: E402

WPS = 2.6  # narration words per second (~155 wpm)
CUE = re.compile(r"<!-- visual-cue (\{.*?\}) -->")


def run(args):
    r = subprocess.run(args, capture_output=True, text=True, check=False)
    if r.returncode:
        raise SystemExit(f"{args[0]} failed: {r.stderr[-1500:].strip()}")
    return r.stdout


def cues(project, ids):
    found = {}
    for m in CUE.finditer((project / "visuals" / "visuals.md").read_text("utf-8")):
        c = json.loads(m.group(1))
        if c["id"] in ids:
            found[c["id"]] = c
    missing = [i for i in ids if i not in found]
    if missing:
        raise SystemExit(f"cue ids not in visuals.md: {', '.join(missing)}")
    return [found[i] for i in ids]


def jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def append(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def starts(lo, hi, n, length, used):
    """n clip starts spread evenly over [lo, hi), skipping used (start, end) ranges."""
    free = [t for t in range(int(lo), int(hi - length))
            if all(t + length <= a or t >= b for a, b in used)]
    if len(free) < n:
        raise SystemExit(f"source too short: need {n} clips, {len(free)} free seconds")
    step = len(free) / n
    picked = []
    for i in range(n):
        t = free[int(i * step + step / 2)]
        if picked and t < picked[-1] + length:
            t = next(f for f in free if f >= picked[-1] + length)
        picked.append(t)
    return picked


def cut(a):
    project, library = Path(a.project), Path(a.library)
    ids = [i.strip() for i in a.cues.split(",") if i.strip()]
    chosen = cues(project, ids)
    cache = project / "media" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    if a.url:
        meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", a.url]))
        src_id, url = meta["id"], meta.get("webpage_url", a.url)
        info = {k: meta.get(k) for k in ("title", "uploader", "license")}
        source = cache / f"{src_id}.mp4"
        if not source.exists():
            run(["yt-dlp", "--ignore-config", "--no-progress", "--no-playlist", "-f",
                 "bv*[height<=1080][height>=720][ext=mp4]/bv*[height<=1080][height>=720]",
                 "--remux-video", "mp4", "-o", str(cache / "%(id)s.%(ext)s"), url])
    else:
        source = Path(a.file)
        src_id, url = re.sub(r"\W", "_", source.stem), source.resolve().as_uri()
        info = {"title": source.name, "uploader": None, "license": None}
    duration = qc.probe(source)["duration"]
    used = [(r["start"], r["end"]) for r in jsonl(library / "library.jsonl") if r.get("url") == url]
    plan = [(c, max(1, round(len(c["anchor"]["quote"].split()) / WPS / a.len))) for c in chosen]
    lo, hi = min(a.skip_head, duration * 0.05), duration - min(a.skip_tail, duration * 0.1)
    times = starts(lo, hi, sum(n for _, n in plan), a.len, used)
    batch = f"{a.pool}-{src_id}"
    lib_dir, broll = library / "youtube" / src_id, project / "B-roll"
    lib_dir.mkdir(parents=True, exist_ok=True)
    broll.mkdir(exist_ok=True)
    taken = {p.name for p in broll.iterdir()}
    clips, k = [], 0
    for c, n in plan:
        for _ in range(n):
            t = times[k]
            k += 1
            lib_file = lib_dir / f"{src_id}_{t}-{t + a.len}.mp4"
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(source),
                 "-t", str(a.len), "-an", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", str(lib_file)])
            m = qc.measure(lib_file)
            flags = [f for f, bad in [("watermark?", m["static_corners"]), ("frozen", m["frozen"]),
                                      ("black", m["black_ratio"] > 0.3), ("letterbox", m["crop"])] if bad]
            seq = 1
            while f"pool_{a.pool}_{seq:03}.mp4" in taken:
                seq += 1
            name = f"pool_{a.pool}_{seq:03}.mp4"
            taken.add(name)
            shutil.copyfile(lib_file, broll / name)
            clips.append({"n": len(clips) + 1, "cue_id": c["id"], "line": c["anchor"]["line"],
                          "quote": c["anchor"]["quote"], "match": c["details"].get("match", "subject"),
                          "file": f"B-roll/{name}", "library_file": lib_file.relative_to(library).as_posix(),
                          "start": t, "end": t + a.len, "qc": m, "flags": flags})
    sheets_dir = project / "media" / "pool-batches" / batch
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips):
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(a.len / 2),
             "-i", str(broll / Path(c["file"]).name), "-frames:v", "1", "-vf", "scale=320:180",
             str(sheets_dir / f"{i:03}.jpg")])
    sheets = []
    for s in range(0, len(clips), 16):
        out = sheets_dir / f"sheet{s // 16 + 1}.jpg"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-start_number", str(s),
             "-i", str(sheets_dir / "%03d.jpg"), "-frames:v", "1", "-vf", "tile=4x4", str(out)])
        sheets.append(str(out))
    state = {"batch": batch, "pool": a.pool, "source": str(source), "source_id": src_id, "url": url,
             "library": str(library), **info, "clips": clips, "sheets": sheets}
    (project / "media" / "pool-batches" / f"{batch}.json").write_text(json.dumps(state, indent=1), "utf-8")
    print(f"batch {batch}: {len(clips)} clips for {len(chosen)} cues")
    print("sheets (row-major, 16 per sheet, numbered from 1): " + " ".join(sheets))
    for c in clips:
        if c["flags"]:
            print(f"  #{c['n']} {', '.join(c['flags'])}")
    print(f"next: pool.py commit --project {project} --batch {batch} [--drop N,N]")


def commit(a):
    project = Path(a.project)
    state_path = project / "media" / "pool-batches" / f"{a.batch}.json"
    st = json.loads(state_path.read_text("utf-8"))
    library = Path(st["library"])
    drop = {int(x) for x in a.drop.split(",") if x.strip()} if a.drop else set()
    now = datetime.now(timezone.utc).isoformat()
    manifest, lib_rows, links = [], [], []
    for c in st["clips"]:
        lib_file, proj_file = library / c["library_file"], project / c["file"]
        row = {"file": c["library_file"], "source": "youtube" if st["url"].startswith("http") else "local",
               "url": st["url"], "title": st["title"], "uploader": st["uploader"], "start": c["start"],
               "end": c["end"], "license": st["license"] or "not provided; presumed copyrighted",
               "tags": [st["pool"].lower()], "risk": "fair-use", "added": now}
        if c["n"] in drop:
            proj_file.unlink(missing_ok=True)
            lib_file.unlink(missing_ok=True)
            lib_rows.append({**row, "qc": {"verdict": "reject", "notes": "contact sheet"}, "used_in": []})
            continue
        lib_rows.append({**row, "sha256": sha(lib_file), "qc": {"verdict": "pass", "notes": "pool contact sheet"},
                         "used_in": [project.name]})
        manifest.append({"cue_id": c["cue_id"], "file": c["file"], "file_sha256": sha(proj_file),
                         "library_file": c["library_file"], "source_id": st["source_id"], "source_url": st["url"],
                         "title": st["title"], "uploader": st["uploader"], "source_range": [c["start"], c["end"]],
                         "risk_class": "fair-use", "requested_match": c["match"], "achieved_match": c["match"],
                         "qc": c["qc"], "visual_verdict": "pass: pool contact sheet", "status": "accepted",
                         "batch": st["batch"]})
        links.append({"line": c["line"], "quote": c["quote"], "media": c["file"]})
    append(project / "media" / "manifest.jsonl", manifest)
    append(library / "library.jsonl", lib_rows)
    if not a.keep_cache and st["url"].startswith("http"):
        Path(st["source"]).unlink(missing_ok=True)
    state_path.replace(state_path.with_suffix(".committed.json"))
    print(f"kept {len(links)}, dropped {len(drop)}")
    print(json.dumps({"links": links}, ensure_ascii=False))


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj, lib = tmp / "proj", tmp / "lib"
        (proj / "visuals").mkdir(parents=True)
        cue = lambda i, line, words: "<!-- visual-cue " + json.dumps(
            {"id": i, "anchor": {"line": line, "quote": " ".join(["word"] * words)},
             "details": {"match": "subject"}}) + " -->"
        (proj / "visuals" / "visuals.md").write_text(
            "# V\n\n## A\n" + cue("c1", 5, 10) + "\n\n## B\n" + cue("c2", 7, 30) + "\n", "utf-8")
        src = tmp / "src.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "testsrc2=size=1280x720:rate=24:duration=120", "-c:v", "libx264", "-preset", "ultrafast", str(src)])
        base = ["--project", str(proj)]
        main(["cut", *base, "--pool", "T", "--cues", "c1,c2", "--file", str(src), "--library", str(lib),
              "--skip-head", "5", "--skip-tail", "5"])
        st = json.loads((proj / "media/pool-batches/T-src.json").read_text("utf-8"))
        assert [c["cue_id"] for c in st["clips"]] == ["c1", "c2", "c2"], st["clips"]
        s = [c["start"] for c in st["clips"]]
        assert all(b >= a + 5 for a, b in zip(s, s[1:])), s
        assert Path(st["sheets"][0]).exists()
        main(["commit", *base, "--batch", "T-src", "--drop", "2"])
        assert not (proj / st["clips"][1]["file"]).exists()
        assert len(jsonl(proj / "media/manifest.jsonl")) == 2
        lib_rows = jsonl(lib / "library.jsonl")
        assert [r["qc"]["verdict"] for r in lib_rows] == ["pass", "reject", "pass"]
        # A second batch from the same source avoids the ranges already used.
        main(["cut", *base, "--pool", "T", "--cues", "c1", "--file", str(src), "--library", str(lib),
              "--skip-head", "5", "--skip-tail", "5"])
        st2 = json.loads((proj / "media/pool-batches/T-src.json").read_text("utf-8"))
        t = st2["clips"][0]["start"]
        assert all(t + 5 <= r["start"] or t >= r["end"] for r in lib_rows), t
        assert st2["clips"][0]["file"] == "B-roll/pool_T_002.mp4"  # dropped name is free again, st2["clips"][0]["file"]
    print("self-test passed")


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("cut")
    c.add_argument("--project", required=True)
    c.add_argument("--pool", required=True)
    c.add_argument("--cues", required=True)
    src = c.add_mutually_exclusive_group(required=True)
    src.add_argument("--url")
    src.add_argument("--file")
    c.add_argument("--library", default=r"D:\SpearFia\library")
    c.add_argument("--len", type=int, default=5)
    c.add_argument("--skip-head", type=float, default=60)
    c.add_argument("--skip-tail", type=float, default=120)
    m = sub.add_parser("commit")
    m.add_argument("--project", required=True)
    m.add_argument("--batch", required=True)
    m.add_argument("--drop", default="")
    m.add_argument("--keep-cache", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    {"cut": cut, "commit": commit}[a.cmd](a)


if __name__ == "__main__":
    main(sys.argv[1:])
