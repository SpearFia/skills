# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fill a Spear Fia project's LIVE footage cues from long source videos with a few calls.

Usage:
  python pool.py auto --project P [--limit 3] [--library D:/SpearFia/library]
      Finds LIVE cues with no link (state comes from links.json, so it always resumes),
      groups them by Subject, and for each group (at most --limit per run):
        1. reuses passing library clips with the same Subject, not used in this project;
        2. otherwise searches YouTube with the cue's first Search phrase and picks a source
           by filters (long, 720p+, not age-restricted, no reaction/commentary words);
        3. cuts clips spread across it, recutting clips QC flags as black/frozen and, once,
           as possible watermark;
        4. writes 4x4 contact sheets.
      Exact cues get one search each and fall back to clips from that video.
      Prints one line per batch: sheet paths and clips still flagged.
  python pool.py commit --project P [--drop BATCH:3,7] [--drop BATCH:all] [--no-link]
      Commits every pending batch: deletes dropped clips (BATCH:all rejects the source so
      `auto` won't pick it again), writes manifest and library, links the clips through
      `spearfia mcp` (links_add), deletes cached sources and rewrites
      production/media-report.md. --no-link prints the links_add payload instead.
  python pool.py status --project P      cues filled per chapter (from links.json)
  python pool.py cut --project P --pool NAME --cues ID,... (--url URL | --file PATH)
      Manual batch from a source you picked; commit it with `commit`.
  python pool.py --self-test

Needs yt-dlp, ffmpeg and ffprobe; links need spearfia.exe (SPEARFIA_EXE, PATH, or the
default build path). Standard library only.
"""

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qc  # noqa: E402

WPS = 2.6  # narration words per second (~155 wpm)
CUE = re.compile(r"<!-- visual-cue (\{.*?\}) -->")
HEAD = re.compile(r"^## (.+)$", re.M)
REJECT_WORDS = re.compile(r"\b(reacts?|reaction|review|explained|breakdown|theory|amv|fan ?made|"
                          r"concept|lyrics|meme|#?shorts|tiktok|podcast|live ?stream|commentary|"
                          r"ranking|top \d+|tier list)\b", re.I)
NO_COMMENTARY = re.compile(r"no commentary", re.I)
DEFAULT_EXE = r"C:\dev\spearfia\spearfia\target\release\spearfia.exe"


def run(args):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if r.returncode:
        raise SystemExit(f"{args[0]} failed: {r.stderr[-1500:].strip()}")
    return r.stdout


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


def slug(text, n=20):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-") or "pool"


def all_cues(project):
    """LIVE and other cues in document order, each with its chapter (heading before ' - ')."""
    text = (project / "visuals" / "visuals.md").read_text("utf-8")
    heads = [(m.start(), m.group(1).split(" - ")[0].strip()) for m in HEAD.finditer(text)]
    out = []
    for m in CUE.finditer(text):
        c = json.loads(m.group(1))
        c["chapter"] = next((h for pos, h in reversed(heads) if pos < m.start()), "")
        out.append(c)
    return out


def links(project):
    p = project / "links.json"
    return json.loads(p.read_text("utf-8")).get("links", []) if p.exists() else []


def unfilled(project):
    quotes = {l["quote"] for l in links(project)}
    return [c for c in all_cues(project) if c.get("method") == "LIVE footage" and c["anchor"]["quote"] not in quotes]


def clips_needed(cue, length):
    if "_need" in cue:  # set by gaps(): extra clips for a stretch the timeline left uncovered
        return cue["_need"]
    return max(1, round(len(cue["anchor"]["quote"].split()) / WPS / length))


def gaps(project, length, min_gap=1.0):
    """LIVE cues whose stretch in the newest pushed plan isn't covered, with _need set to the
    clips that would cover it. Uses real voiceover timing, so run it after a push."""
    plans = sorted((project / "sync" / "plans").glob("plan-*.json"), key=lambda p: p.stat().st_mtime)
    if not plans:
        raise SystemExit("no pushed plan yet: run `spearfia push filmcraft` first")
    plan = json.loads(plans[-1].read_text("utf-8"))
    fps = plan["timebase"]["num"] / plan["timebase"]["den"]
    quote_of = {l["id"]: l["quote"] for l in links(project)}
    spans = {}
    for it in plan["items"]:
        if it["kind"] != "clip" or it["track"] != "V2" or it["cue_id"] not in quote_of:
            continue
        end = it["start_frame"] + (it.get("intent") or {}).get("duration_frames", it["duration_frames"])
        s = spans.setdefault(quote_of[it["cue_id"]], [it["start_frame"], end, 0])
        s[0], s[1], s[2] = min(s[0], it["start_frame"]), max(s[1], end), s[2] + it["duration_frames"]
    cues = all_cues(project)
    out = []
    for c in cues:
        s = spans.get(c["anchor"]["quote"]) if c.get("method") == "LIVE footage" else None
        missing = (s[1] - s[0] - s[2]) / fps if s else 0
        if missing >= min_gap:
            out.append({**c, "_need": max(1, round(missing / length))})
    # Stretches outside every footage cue (under a card, before a section's first clip) go to
    # the unlinked cue sitting there, filled from the neighbouring footage cue's pool.
    order = {c["anchor"]["quote"]: i for i, c in enumerate(cues)}
    pics = sorted((it["start_frame"], it["start_frame"] + it["duration_frames"], order.get(quote_of.get(it["cue_id"]), -1))
                  for it in plan["items"] if it["kind"] == "clip" and it["track"] == "V2")
    vo_end = max((it["start_frame"] + it["duration_frames"] for it in plan["items"]
                  if it["kind"] == "clip" and it["track"] == "A1"), default=0)
    covered = sorted([(a, b) for a, b, _ in pics] + [(s[0], s[1]) for s in spans.values()])
    holes, at = [], 0
    for a, b in covered + [(vo_end, vo_end)]:
        if a - at >= min_gap * fps:
            holes.append((at, min(a, vo_end)))
        at = max(at, b)
    # The push's edit listing gives each card's cue and time, and each section start.
    listing = plans[-1].with_suffix(".edit.txt")
    card_at, section_at = {}, []
    for line in (listing.read_text("utf-8").splitlines() if listing.exists() else []):
        m = re.match(r"(\d+):(\d\d)\s+rule (generated (\S+)|section)", line)
        if m:
            t = (int(m.group(1)) * 60 + int(m.group(2))) * fps
            (section_at.append(t) if m.group(3) == "section" else card_at.__setitem__(m.group(4), t))
    linked = set(quote_of.values())
    extra = {}
    for a, b in holes:
        before = [p[2] for p in pics if p[1] <= a and p[2] >= 0]
        after = [p[2] for p in pics if p[0] >= b and p[2] >= 0]
        lo, hi = (before[-1] if before else -1), (after[0] if after else len(cues))
        # Listed times are whole seconds, so a card up to 1 s before the hole counts as in it.
        spot = [c for c in cues[lo + 1:hi] if c["anchor"]["quote"] not in linked
                and a - fps <= card_at.get(c["id"], -1e9) < b]
        for t in spot:  # each takes a share: the previous section's footage before a section start, else the next
            ends_section = any(card_at[t["id"]] < s <= b for s in section_at)
            ref = next((cues[i] for i in ((lo, hi) if ends_section else (hi, lo)) if 0 <= i < len(cues)
                        and cues[i].get("method") == "LIVE footage" and cues[i]["details"].get("Subject")), None)
            if ref:
                e = extra.setdefault(t["id"], {**t, "details": {**ref["details"], "match": "subject"}, "_need": 0})
                e["_need"] += max(1, round((b - a) / fps / length / len(spot)))
    return out + list(extra.values())


def free_times(lo, hi, length, used):
    return [t for t in range(int(lo), int(hi - length)) if all(t + length <= a or t >= b for a, b in used)]


def starts(lo, hi, n, length, used):
    """n clip starts spread evenly over [lo, hi), skipping used (start, end) ranges."""
    free = free_times(lo, hi, length, used)
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


def flags_of(m):
    return [f for f, bad in [("black", m["black_ratio"] > 0.3), ("frozen", m["frozen"]),
                             ("watermark?", m["static_corners"]), ("letterbox", m["crop"])] if bad]


def fetch(url, cache):
    meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", url]))
    source = cache / f"{meta['id']}.mp4"
    if not source.exists():
        run(["yt-dlp", "--ignore-config", "--no-progress", "--no-playlist", "-f",
             "bv*[height<=1080][height>=720][ext=mp4]/bv*[height<=1080][height>=720]",
             "--remux-video", "mp4", "-o", str(cache / "%(id)s.%(ext)s"), url])
    return source, meta["id"], meta.get("webpage_url", url), {k: meta.get(k) for k in ("title", "uploader", "license")}


def pick_source(query, min_dur, excluded):
    """First search hit that passes the filters: long enough, 720p+, not age-restricted."""
    out = run(["yt-dlp", "--ignore-config", "--flat-playlist", "--dump-json", f"ytsearch10:{query}"])
    hits = [json.loads(l) for l in out.splitlines() if l.strip()]
    ok = [h for h in hits if h.get("id") not in excluded and (h.get("duration") or 0) >= min_dur
          and not REJECT_WORDS.search(NO_COMMENTARY.sub("", f"{h.get('title', '')} {h.get('channel', '')}"))]
    for h in ok[:4]:
        try:
            meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", h["url"]]))
        except SystemExit:
            continue  # age gate, private, removed
        if (meta.get("age_limit") or 0) == 0 and any((f.get("height") or 0) >= 720 for f in meta.get("formats", [])):
            return meta.get("webpage_url", h["url"])
    return None


def make_batch(project, library, pool, chosen, source, src_id, url, info, length=5, skip_head=60.0,
               skip_tail=120.0, reuse=(), seed=0):
    """Cut (or reuse) clips for chosen cues, recut bad ones, write sheets and the batch file."""
    broll = project / "B-roll"
    broll.mkdir(exist_ok=True)
    taken = {p.name for p in broll.iterdir()}

    def name():
        seq = 1
        while f"pool_{pool}_{seq:03}.mp4" in taken:
            seq += 1
        taken.add(f"pool_{pool}_{seq:03}.mp4")
        return f"pool_{pool}_{seq:03}.mp4"

    reuse = list(reuse)
    need = [(c, clips_needed(c, length)) for c in chosen]
    clips, rest = [], []
    for c, n in need:  # library clips first
        while n and reuse:
            r = reuse.pop(0)
            dst = name()
            shutil.copyfile(library / r["file"], broll / dst)
            clips.append({"n": len(clips) + 1, "cue_id": c["id"], "line": c["anchor"]["line"],
                          "quote": c["anchor"]["quote"], "match": c["details"].get("match", "subject"),
                          "file": f"B-roll/{dst}", "library_file": r["file"], "start": r["start"],
                          "end": r["end"], "qc": None, "flags": [], "reused": True,
                          "source_url": r.get("url"), "title": r.get("title"), "uploader": r.get("uploader")})
            n -= 1
        rest.append((c, n))
    need = rest
    total = sum(n for _, n in need)
    if total:
        duration = qc.probe(source)["duration"]
        used = [(r["start"], r["end"]) for r in jsonl(library / "library.jsonl") if r.get("url") == url]
        lo, hi = min(skip_head, duration * 0.05), duration - min(skip_tail, duration * 0.1)
        times = iter(starts(lo, hi, total, length, used))
        rng = random.Random(seed)
        lib_dir = library / "youtube" / src_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        for c, n in need:
            for _ in range(n):
                t, tries = next(times), 0
                while True:
                    lib_file = lib_dir / f"{src_id}_{t}-{t + length}.mp4"
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(source),
                         "-t", str(length), "-an", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", str(lib_file)])
                    m = qc.measure(lib_file)
                    fl = flags_of(m)
                    bad = {"black", "frozen"} & set(fl) or ("watermark?" in fl and tries < 1)
                    if not bad or tries >= 3:
                        break
                    lib_file.unlink()
                    used.append((t, t + length))
                    free = free_times(lo, hi, length, used + [(x["start"], x["end"]) for x in clips])
                    if not free:
                        break
                    t, tries = rng.choice(free), tries + 1
                used.append((t, t + length))
                dst = name()
                shutil.copyfile(lib_file, broll / dst)
                clips.append({"n": len(clips) + 1, "cue_id": c["id"], "line": c["anchor"]["line"],
                              "quote": c["anchor"]["quote"], "match": c["details"].get("match", "subject"),
                              "file": f"B-roll/{dst}", "library_file": lib_file.relative_to(library).as_posix(),
                              "start": t, "end": t + length, "qc": m, "flags": fl})
    # Pool slugs are short, so two pools (or two runs) can share a name: never reuse a batch's file.
    bdir, batch, k = project / "media" / "pool-batches", f"{pool}-{src_id}", 1
    while (bdir / f"{batch}.json").exists() or (bdir / f"{batch}.committed.json").exists():
        k += 1
        batch = f"{pool}-{src_id}-{k}"
    sheets_dir = project / "media" / "pool-batches" / batch
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips):
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(length / 2),
             "-i", str(project / c["file"]), "-frames:v", "1", "-vf", "scale=320:180", str(sheets_dir / f"{i:03}.jpg")])
    sheets = []
    for s in range(0, len(clips), 16):
        out = sheets_dir / f"sheet{s // 16 + 1}.jpg"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-start_number", str(s),
             "-i", str(sheets_dir / "%03d.jpg"), "-frames:v", "1", "-vf", "tile=4x4", str(out)])
        sheets.append(str(out))
    subject = chosen[0]["details"].get("Subject", "") if chosen else ""
    state = {"batch": batch, "pool": pool, "subject": subject, "source": str(source) if source else None,
             "source_id": src_id, "url": url, "library": str(library), **info, "clips": clips, "sheets": sheets}
    (project / "media" / "pool-batches" / f"{batch}.json").write_text(json.dumps(state, indent=1), "utf-8")
    flagged = " ".join(f"#{c['n']}({','.join(c['flags'])})" for c in clips if c["flags"])
    print(f"{batch}: {len(clips)} clips, {len(chosen)} cues | {' '.join(sheets)}" + (f" | flagged {flagged}" if flagged else ""))
    return state


def auto(a):
    project, library = Path(a.project), Path(a.library)
    cache = project / "media" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    pending = {p.stem for p in (project / "media" / "pool-batches").glob("*.json")
               if not p.stem.endswith(".committed") and p.stem != "excluded"}
    if pending:
        raise SystemExit(f"commit or drop the pending batches first: {', '.join(sorted(pending))}")
    empty = gaps(project, a.len) if a.fill_gaps else unfilled(project)
    if not empty:
        print("no uncovered stretches in the newest plan" if a.fill_gaps else "all LIVE cues are linked")
        return
    excluded_path = project / "media" / "pool-batches" / "excluded.json"
    excluded = set(json.loads(excluded_path.read_text("utf-8"))) if excluded_path.exists() else set()
    lib_rows = jsonl(library / "library.jsonl")
    in_use = {r["file"] for r in lib_rows if project.name in r.get("used_in", [])}
    groups = {}
    for c in empty:  # exact cues each get their own group and source
        key = c["id"] if c["details"].get("match") == "exact" else c["details"].get("Subject", c["chapter"])
        groups.setdefault(key, []).append(c)
    done = 0
    for key, chosen in groups.items():
        if done >= a.limit:
            break
        subject = chosen[0]["details"].get("Subject", "")
        exact = chosen[0]["details"].get("match") == "exact"
        pool = slug(subject or chosen[0]["chapter"])
        ok = [r for r in lib_rows if r.get("subject") == subject and r.get("qc", {}).get("verdict") == "pass"
              and (library / r["file"]).exists()] if subject else []
        reuse = [r for r in ok if r["file"] not in in_use]
        if a.fill_gaps:  # filler may repeat this video's own clips (least used first) before downloading
            uses = Counter(m.get("library_file") for m in jsonl(project / "media" / "manifest.jsonl"))
            reuse += sorted((r for r in ok if r["file"] in in_use), key=lambda r: uses[r["file"]])
        need = sum(clips_needed(c, a.len) for c in chosen)
        source = src_id = url = None
        info = {"title": "library", "uploader": None, "license": None}
        if len(reuse) < need:
            query = (chosen[0]["details"].get("Search", "") or subject).split("|")[0].strip()
            url = pick_source(query, 30 if exact else 600, excluded)
            if not url and exact:  # lax fallback: the pool's own search
                url = pick_source(subject, 600, excluded)
            if not url:
                print(f"{pool}: no source passed the filters for {query!r}; {len(chosen)} cues left")
                continue
            source, src_id, url, info = fetch(url, cache)
        make_batch(project, library, pool, chosen, source, src_id or "library", url, info, a.len,
                   reuse=reuse[:need])
        done += 1
    left = len(groups) - done
    print(f"next: look at each sheet once, then pool.py commit --project {project} [--drop BATCH:N,N | BATCH:all]"
          + (f"; {left} more groups after that (run auto again)" if left else ""))


def cut(a):
    project, library = Path(a.project), Path(a.library)
    ids = [i.strip() for i in a.cues.split(",") if i.strip()]
    by_id = {c["id"]: c for c in all_cues(project)}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"cue ids not in visuals.md: {', '.join(missing)}")
    cache = project / "media" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    if a.url:
        source, src_id, url, info = fetch(a.url, cache)
    else:
        source = Path(a.file)
        src_id, url = re.sub(r"\W", "_", source.stem), source.resolve().as_uri()
        info = {"title": source.name, "uploader": None, "license": None}
    make_batch(project, library, a.pool, [by_id[i] for i in ids], source, src_id, url, info, a.len,
               a.skip_head, a.skip_tail)


def spearfia_cmd():
    if os.environ.get("SPEARFIA_CMD"):  # JSON list, used by the self-test
        return json.loads(os.environ["SPEARFIA_CMD"])
    exe = os.environ.get("SPEARFIA_EXE") or shutil.which("spearfia") or DEFAULT_EXE
    return [exe]


def links_add(project, payload):
    """Call links_add through `spearfia mcp` over stdio; returns the new link ids."""
    p = subprocess.Popen(spearfia_cmd() + ["mcp", "--project", str(project)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=project)

    def rpc(i, method, params):
        p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n").encode())
        p.stdin.flush()
        while True:
            line = p.stdout.readline()
            if not line:
                raise SystemExit("spearfia mcp closed the connection")
            r = json.loads(line)
            if r.get("id") == i:
                return r

    try:
        rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "pool.py", "version": "1"}})
        p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        r = rpc(2, "tools/call", {"name": "links_add", "arguments": payload})
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    res = r.get("result") or {}
    if "error" in r or res.get("isError"):
        raise SystemExit(f"links_add failed: {json.dumps(r.get('error') or res.get('content'))[:800]}")
    data = res.get("structuredContent") or json.loads(res["content"][0]["text"])
    return data.get("ids", [])


def report(project):
    linked_quotes = {l["quote"] for l in links(project)}
    rows, empty = {}, []
    for c in all_cues(project):
        if c.get("method") != "LIVE footage":
            continue
        r = rows.setdefault(c["chapter"], [0, 0])
        r[0] += 1
        if c["anchor"]["quote"] in linked_quotes:
            r[1] += 1
        else:
            empty.append(f"- {c['chapter']}: {c['id']} ({c['details'].get('match', 'subject')})")
    lines = ["# Media report", "", f"Generated by pool.py {datetime.now().isoformat(timespec='minutes')} from links.json.",
             "", "| Chapter | LIVE cues | Linked |", "| --- | --- | --- |"]
    lines += [f"| {ch} | {n} | {k} |" for ch, (n, k) in rows.items()]
    total, filled = sum(n for n, _ in rows.values()), sum(k for _, k in rows.values())
    lines += ["", f"Total: {filled} of {total} linked.", ""] + (["## Unfilled", ""] + empty if empty else [])
    out = project / "production" / "media-report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", "utf-8")
    return filled, total


def status(a):
    filled, total = report(Path(a.project))
    print(f"{filled} of {total} LIVE cues linked; details in production/media-report.md")


def commit(a):
    project = Path(a.project)
    bdir = project / "media" / "pool-batches"
    batches = sorted(p for p in bdir.glob("*.json") if not p.stem.endswith(".committed") and p.stem != "excluded")
    if a.batch:
        batches = [bdir / f"{a.batch}.json"]
    drops = {}
    for d in a.drop:
        b, _, nums = d.partition(":")
        drops[b] = "all" if nums.strip() == "all" else {int(x) for x in nums.split(",") if x.strip()}
    excluded_path = bdir / "excluded.json"
    excluded = set(json.loads(excluded_path.read_text("utf-8"))) if excluded_path.exists() else set()
    now = datetime.now(timezone.utc).isoformat()
    payload, manifest, kept_total = [], [], 0
    for state_path in batches:
        st = json.loads(state_path.read_text("utf-8"))
        library = Path(st["library"])
        drop = drops.get(st["batch"], set())
        if drop == "all":
            excluded.add(st["source_id"])
            drop = {c["n"] for c in st["clips"]}
        lib_rows, reused = [], set()
        for c in st["clips"]:
            lib_file, proj_file = library / c["library_file"], project / c["file"]
            if c.get("reused"):
                if c["n"] in drop:
                    proj_file.unlink(missing_ok=True)
                    continue
                reused.add(c["library_file"])
            else:
                row = {"file": c["library_file"], "source": "youtube" if str(st["url"]).startswith("http") else "local",
                       "url": st["url"], "title": st["title"], "uploader": st["uploader"], "start": c["start"],
                       "end": c["end"], "license": st["license"] or "not provided; presumed copyrighted",
                       "subject": st.get("subject", ""), "tags": [st["pool"].lower()], "risk": "fair-use", "added": now}
                if c["n"] in drop:
                    proj_file.unlink(missing_ok=True)
                    lib_file.unlink(missing_ok=True)
                    lib_rows.append({**row, "qc": {"verdict": "reject", "notes": "contact sheet"}, "used_in": []})
                    continue
                cr = (c["qc"] or {}).get("crop")
                if cr:  # letterbox/pillarbox: crop the bars out of both copies
                    for f in (proj_file, lib_file):
                        tmpf = f.with_name(f.stem + "_crop.mp4")
                        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(f), "-vf",
                             f"crop={cr['w']}:{cr['h']}:{cr['x']}:{cr['y']}", "-an", "-c:v", "libx264",
                             "-crf", "18", "-preset", "fast", str(tmpf)])
                        tmpf.replace(f)
                lib_rows.append({**row, "sha256": sha(lib_file), "qc": {"verdict": "pass", "notes": "pool contact sheet"},
                                 "used_in": [project.name]})
            manifest.append({"cue_id": c["cue_id"], "file": c["file"], "file_sha256": sha(proj_file),
                             "library_file": c["library_file"], "source_id": st["source_id"],
                             "source_url": c.get("source_url") or st["url"], "title": c.get("title") or st["title"],
                             "uploader": c.get("uploader") or st["uploader"], "source_range": [c["start"], c["end"]],
                             "risk_class": "fair-use", "requested_match": c["match"], "achieved_match":
                             c["match"] if c["match"] != "exact" else "subject (lax exact)",
                             "qc": c["qc"], "visual_verdict": "pass: pool contact sheet", "status": "accepted",
                             "batch": st["batch"], "reused": bool(c.get("reused"))})
            payload.append({"line": c["line"], "quote": c["quote"], "media": c["file"]})
            kept_total += 1
        if reused:  # mark reused library clips as used in this project
            all_rows = jsonl(library / "library.jsonl")
            for r in all_rows:
                if r["file"] in reused and project.name not in r.setdefault("used_in", []):
                    r["used_in"].append(project.name)
            (library / "library.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows), "utf-8")
        append(library / "library.jsonl", lib_rows)
        if not a.keep_cache and st.get("source") and str(st["url"]).startswith("http"):
            Path(st["source"]).unlink(missing_ok=True)
        state_path.replace(state_path.with_suffix(".committed.json"))
    excluded_path.parent.mkdir(parents=True, exist_ok=True)
    excluded_path.write_text(json.dumps(sorted(excluded)), "utf-8")
    if a.no_link:
        append(project / "media" / "manifest.jsonl", manifest)
        print(json.dumps({"links": payload}, ensure_ascii=False))
        return
    ids = links_add(project, {"links": payload}) if payload else []
    for m, i in zip(manifest, ids):
        m["link_id"] = i
    append(project / "media" / "manifest.jsonl", manifest)
    filled, total = report(project)
    print(f"committed {len(batches)} batches, linked {len(ids)} clips; {filled} of {total} LIVE cues linked"
          + ("; run auto again" if filled < total else ""))


FAKE_MCP = r'''
import json, sys, pathlib
proj = pathlib.Path(sys.argv[sys.argv.index("--project") + 1])
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    if m["method"] == "tools/call":
        p = proj / "links.json"
        d = json.loads(p.read_text()) if p.exists() else {"links": []}
        new = m["params"]["arguments"]["links"]
        ids = [f"k{len(d['links']) + i + 1}" for i in range(len(new))]
        d["links"] += [{"id": i, "line": l["line"], "quote": l["quote"], "media": {"path": l["media"]}} for i, l in zip(ids, new)]
        p.write_text(json.dumps(d))
        res = {"structuredContent": {"ids": ids}}
    else:
        res = {}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}), flush=True)
'''


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj, lib = tmp / "proj", tmp / "lib"
        (proj / "visuals").mkdir(parents=True)
        cue = lambda i, line, words, subject="Game A", match="subject": "<!-- visual-cue " + json.dumps(
            {"id": i, "method": "LIVE footage", "anchor": {"line": line, "quote": f"q{i} " + " ".join(["word"] * words)},
             "details": {"match": match, "Subject": subject, "Search": "game a all cutscenes"}}) + " -->"
        (proj / "visuals" / "visuals.md").write_text(
            "# V\n\n## A - one\n" + cue("c1", 5, 10) + "\n\n## B - two\n" + cue("c2", 7, 30) + "\n", "utf-8")
        src = tmp / "src.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "testsrc2=size=1280x720:rate=24:duration=120", "-c:v", "libx264", "-preset", "ultrafast", str(src)])
        fake = tmp / "fake_mcp.py"
        fake.write_text(FAKE_MCP, "utf-8")
        os.environ["SPEARFIA_CMD"] = json.dumps([sys.executable, str(fake)])
        base = ["--project", str(proj)]
        main(["cut", *base, "--pool", "T", "--cues", "c1,c2", "--file", str(src), "--library", str(lib),
              "--skip-head", "5", "--skip-tail", "5"])
        st = json.loads((proj / "media/pool-batches/T-src.json").read_text("utf-8"))
        assert [c["cue_id"] for c in st["clips"]] == ["c1", "c2", "c2"], st["clips"]
        s = [c["start"] for c in st["clips"]]
        assert all(b >= a + 5 for a, b in zip(s, s[1:])), s
        assert Path(st["sheets"][0]).exists()
        main(["commit", *base, "--drop", "T-src:2"])
        assert not (proj / st["clips"][1]["file"]).exists()
        assert len(links(proj)) == 2 and not unfilled(proj)
        man = jsonl(proj / "media/manifest.jsonl")
        assert [m["link_id"] for m in man] == ["k1", "k2"], man
        assert "2 of 2" in (proj / "production/media-report.md").read_text("utf-8")
        lib_rows = jsonl(lib / "library.jsonl")
        assert [r["qc"]["verdict"] for r in lib_rows] == ["pass", "reject", "pass"]
        assert all(r["subject"] == "Game A" for r in lib_rows)
        # A second project reuses the library clips for the same Subject without downloading.
        proj2 = tmp / "proj2"
        (proj2 / "visuals").mkdir(parents=True)
        (proj2 / "visuals" / "visuals.md").write_text("## X - one\n" + cue("d1", 3, 20) + "\n", "utf-8")
        main(["auto", "--project", str(proj2), "--library", str(lib)])
        st2 = json.loads((proj2 / "media/pool-batches/game-a-library.json").read_text("utf-8"))
        # A second batch with the same pool and source gets its own name instead of overwriting.
        make_batch(proj2, lib, "game-a", [], None, "library", None, {"title": "library", "uploader": None, "license": None})
        assert (proj2 / "media/pool-batches/game-a-library-2.json").exists()
        (proj2 / "media/pool-batches/game-a-library-2.json").unlink()
        assert len(st2["clips"]) == 2 and all(c["reused"] for c in st2["clips"]), st2["clips"]
        main(["commit", "--project", str(proj2)])
        assert not unfilled(proj2)
        assert all("proj2" in r["used_in"] for r in jsonl(lib / "library.jsonl") if r["qc"]["verdict"] == "pass")
        # gaps(): a plan where c1's stretch is 600 frames but its clips cover 150 needs 15 s more.
        (proj / "sync" / "plans").mkdir(parents=True)
        (proj / "sync" / "plans" / "plan-1.json").write_text(json.dumps({"timebase": {"num": 30, "den": 1}, "items": [
            {"kind": "clip", "track": "V2", "cue_id": "k1", "start_frame": 0, "duration_frames": 150,
             "intent": {"start_frame": 0, "duration_frames": 600}}]}), "utf-8")
        g = gaps(proj, 5)
        assert [(c["id"], c["_need"]) for c in g] == [("c1", 3)], g
        # gaps(): 10 s with no picture under a card before c1 goes to the card's cue, from c1's pool.
        proj3 = tmp / "proj3"
        (proj3 / "visuals").mkdir(parents=True)
        card = "<!-- visual-cue " + json.dumps({"id": "g1", "method": "Generated artwork",
                                                 "anchor": {"line": 3, "quote": "ROUND ONE"}, "details": {}}) + " -->"
        (proj3 / "visuals" / "visuals.md").write_text("## A - one\n" + card + "\n" + cue("c1", 5, 10) + "\n", "utf-8")
        (proj3 / "links.json").write_text(json.dumps({"links": [
            {"id": "k1", "line": 5, "quote": "qc1 " + " ".join(["word"] * 10), "media": {"path": "B-roll/a.mp4"}}]}), "utf-8")
        (proj3 / "sync" / "plans").mkdir(parents=True)
        (proj3 / "sync" / "plans" / "plan-1.json").write_text(json.dumps({"timebase": {"num": 30, "den": 1}, "items": [
            {"kind": "clip", "track": "A1", "cue_id": "vo", "start_frame": 0, "duration_frames": 900},
            {"kind": "clip", "track": "V2", "cue_id": "k1", "start_frame": 300, "duration_frames": 600}]}), "utf-8")
        (proj3 / "sync" / "plans" / "plan-1.edit.txt").write_text(
            '0:00  rule generated g1 Card { text: Some("ROUND ONE"), seconds: None }\n', "utf-8")
        g = gaps(proj3, 5)
        assert [(c["id"], c["_need"], c["details"]["Subject"]) for c in g] == [("g1", 2, "Game A")], g
        # BATCH:all rejects the source.
        main(["cut", *base, "--pool", "T", "--cues", "c1", "--file", str(src), "--library", str(lib),
              "--skip-head", "5", "--skip-tail", "5"])
        main(["commit", *base, "--drop", "T-src-2:all", "--no-link"])
        assert json.loads((proj / "media/pool-batches/excluded.json").read_text()) == ["src"]
        # Bad clips are recut: a black stretch at 50-80 s never survives as a black clip.
        blk = tmp / "blk.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "testsrc2=size=1280x720:rate=24:duration=120", "-vf", "drawbox=enable='between(t,50,80)':c=black:t=fill",
             "-c:v", "libx264", "-preset", "ultrafast", str(blk)])
        (proj / "visuals" / "visuals.md").write_text("## A - one\n" + cue("e1", 9, 60) + "\n", "utf-8")
        main(["cut", *base, "--pool", "B", "--cues", "e1", "--file", str(blk), "--library", str(tmp / "lib3"),
              "--skip-head", "5", "--skip-tail", "5"])
        st3 = json.loads((proj / "media/pool-batches/B-blk.json").read_text("utf-8"))
        assert not any("black" in c["flags"] for c in st3["clips"]), [(c["start"], c["flags"]) for c in st3["clips"]]
        assert slug("Resident Evil 2 remake Mr. X (Tyrant)") == "resident-evil-2-rema"
        assert REJECT_WORDS.search("Mr X reaction") and not REJECT_WORDS.search(
            NO_COMMENTARY.sub("", "RE2 all cutscenes no commentary"))
    print("self-test passed")


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    au = sub.add_parser("auto")
    au.add_argument("--project", required=True)
    au.add_argument("--library", default=r"D:\SpearFia\library")
    au.add_argument("--limit", type=int, default=3, help="groups per run (each may download a long video)")
    au.add_argument("--len", type=int, default=5)
    au.add_argument("--fill-gaps", action="store_true",
                    help="after a push: add clips where the timeline shows uncovered picture time")
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
    m.add_argument("--batch", default="", help="only this batch (default: every pending batch)")
    m.add_argument("--drop", action="append", default=[], help="BATCH:N,N or BATCH:all; repeatable")
    m.add_argument("--keep-cache", action="store_true")
    m.add_argument("--no-link", action="store_true", help="print the links_add payload instead of linking")
    s = sub.add_parser("status")
    s.add_argument("--project", required=True)
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    {"auto": auto, "cut": cut, "commit": commit, "status": status}[a.cmd](a)


if __name__ == "__main__":
    main(sys.argv[1:])
