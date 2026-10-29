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
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qc  # noqa: E402

WPS = 2.6  # narration words per second (~155 wpm)
CUE = re.compile(r"<!-- visual-cue (\{.*?\}) -->")
HEAD = re.compile(r"^## (.+)$", re.M)
REJECT_WORDS = re.compile(r"\b(reacts?|reaction|review|explained|breakdown|theory|amv|fan ?made|"
                          r"concept|lyrics|meme|#?shorts|tiktok|podcast|live ?stream|commentary|"
                          r"ranking|top \d+|tier list|parody|challenge|i beat|speedrun|mods?|but it'?s)\b", re.I)
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


def spoken_quote(text):
    return re.sub(r"\[[a-z]+\]\s*", "", re.sub(r"^VO:\s*", "", text))


def all_cues(project):
    """LIVE and other cues in document order, each with its chapter (heading before ' - ')."""
    text = (project / "visuals" / "visuals.md").read_text("utf-8")
    heads = [(m.start(), m.group(1).split(" - ")[0].strip()) for m in HEAD.finditer(text)]
    out = []
    for m in CUE.finditer(text):
        c = json.loads(m.group(1))
        c["anchor"]["quote"] = spoken_quote(c["anchor"]["quote"])
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


def slots(lo, hi, length, used):
    """Every non-overlapping clip start in [lo, hi) that avoids used (start, end) ranges."""
    out = []
    for t in free_times(lo, hi, length, used):
        if not out or t >= out[-1] + length:
            out.append(t)
    return out


def starts(lo, hi, n, length, used):
    """n clip starts spread evenly over [lo, hi), skipping used (start, end) ranges."""
    free = slots(lo, hi, length, used)
    if len(free) < n:
        raise SystemExit(f"source too short: need {n} clips, {len(free)} free slots")
    return [free[int((i + 0.5) * len(free) / n)] for i in range(n)]


def flags_of(m):
    return [f for f, bad in [("black", m["black_ratio"] > 0.3), ("frozen", m["frozen"]),
                             ("watermark?", m["static_corners"]), ("letterbox", m["crop"])] if bad]


def cache_dir(project):
    """Where raw sources download and get cut: a fast local disk (SPEARFIA_CACHE, default
    C:/SpearFia/cache), never the project's drive, which may be a slow external one.
    Sources are deleted after commit; only the finished clips land in the project."""
    d = Path(os.environ.get("SPEARFIA_CACHE", r"C:\SpearFia\cache")) / project.name
    d.mkdir(parents=True, exist_ok=True)
    return d


PROXY_FORMAT = "bv*[height<=480][height>=360][ext=mp4]/bv*[height<=480][height>=360]/bv*[height<=480]"
HQ_FORMAT = "bv*[height<=1080][height>=720]/bv*[height<=1080]"
HQ_MAX = 1080


def fetch(url, cache, full=False):
    """Download a source: a 360-480p proxy for review (about a tenth of the size; kept clips
    are re-cut from the full-quality video by `pool.py upgrade`), or full quality."""
    meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", url]))
    tag = "" if full else ".proxy"
    source = cache / f"{meta['id']}{tag}.mp4"
    if not source.exists():
        run(["yt-dlp", "--ignore-config", "--no-progress", "--no-playlist",
             "--abort-on-unavailable-fragments", "--fragment-retries", "0", "--retries", "0",
             "--socket-timeout", "30", "--concurrent-fragments", "4", "-f",
             HQ_FORMAT if full else PROXY_FORMAT,
             "--remux-video", "mp4", "-o", str(cache / f"%(id)s{tag}.%(ext)s"), url])
    info = {k: meta.get(k) for k in ("title", "uploader", "license", "channel_id")}
    return source, meta["id"], meta.get("webpage_url", url), {**info, "proxy": not full}


RAW_DUMP = re.compile(r"cutscene|cinematic|movie|all scenes", re.I)
FULL_GAME = re.compile(r"longplay|full game|full gameplay|movie|cutscene|cinematic", re.I)
GENERIC = {"resident", "evil", "all", "cutscenes", "cutscene", "cinematics", "cinematic", "4k", "no", "commentary",
           "full", "game", "movie", "gameplay", "walkthrough", "longplay", "the", "of", "and", "or", "bosses", "8k", "60fps"}
DLC = re.compile(r"\bdlc\b|separate ways|shadows of rose|not a hero|end of zoe|gta online|"
                 r"vice city stories|liberty city stories|the lost and damned|ballad of gay tony|cayo perico|the contract heist|trevor'?s heist", re.I)


def load_channels(library):
    """`trusted` (game footage) and `film` (movie and TV scenes) channels are searched first, each
    for its own kind of pool; `watermark` channels are never used."""
    p = library / "channels.json"
    d = json.loads(p.read_text("utf-8")) if p.exists() else {}
    return {"trusted": d.get("trusted", {}), "film": d.get("film", {}), "watermark": d.get("watermark", {}),
            "note": d.get("note", "")}


def footage(cue):
    """The kind of footage a pool needs: its `Footage` detail, `game` unless it says `film`."""
    return "film" if str(cue["details"].get("Footage", "")).strip().lower() == "film" else "game"


def save_channels(library, channels):
    (library / "channels.json").write_text(json.dumps(channels, indent=1, ensure_ascii=False), "utf-8")


def rank(hits, query, min_dur, excluded, banned=(), strict=False, prefer=RAW_DUMP):
    """Hits that pass the filters, best first: the query's game words in the title, no DLC
    unless asked for, cutscene compilations before gameplay, then the longest compilation."""
    ok = [h for h in hits if h.get("id") not in excluded and (h.get("duration") or 0) >= min_dur
          and h.get("channel_id") not in banned and (h.get("channel") or h.get("uploader")) not in banned
          and not REJECT_WORDS.search(NO_COMMENTARY.sub("", f"{h.get('title', '')} {h.get('channel', '')}"))]
    def words(t):
        t = re.sub(r"\bgrand theft auto\b", "gta", t.lower())
        t = re.sub(r"\bgta\s*(iii|iv|vi|v|[3-6])\b",
                   lambda m: "gta" + {"iii": "3", "iv": "4", "v": "5", "vi": "6"}.get(m[1], m[1]), t)
        return set(re.findall(r"[a-z0-9]+", t))
    game = {w for w in words(query) - GENERIC if len(w) > 1 or w.isdigit()}
    same = [h for h in ok if game <= words(h.get("title", ""))]
    ok = same if strict or same else ok  # a channel's other games never stand in for this one
    if re.fullmatch(r'john wick fight scenes?', query, re.I):
        ok = [h for h in same if not re.search(
            r'\b(?:chapter\s*(?:[234]|ii|iii|iv)|john wick\s*[: -]*[234]|2017|2019|2023)\b',
            h.get('title', ''), re.I)]
    if not re.search(r"\bdlc\b", query, re.I):  # DLC and spin-offs only when the Search names them
        ok = [h for h in ok if not (m := DLC.search(h.get("title", ""))) or m.group(0).lower() in query.lower()]
    raw = not re.search(r"walkthrough|gameplay|longplay", query, re.I)
    ok.sort(key=lambda h: (raw and not prefer.search(h.get("title", "")), -(h.get("duration") or 0) if raw else 0))
    return ok


def usable(h):
    """The video's URL if it can be downloaded at 720p+ without an age gate."""
    try:
        meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", h["url"]]))
    except SystemExit:
        return None  # age gate, private, removed
    if (meta.get("age_limit") or 0) == 0 and any((f.get("height") or 0) >= 720 for f in meta.get("formats", [])):
        return meta.get("webpage_url", h["url"])
    return None


def search(target, n=10):
    try:
        out = run(["yt-dlp", "--ignore-config", "--flat-playlist", "--playlist-end", str(n), "--dump-json", target])
    except SystemExit:
        return []
    return [json.loads(l) for l in out.splitlines() if l.strip()]


HANDLE = 2.5  # seconds of spare footage cut on each side of a clip's shot; its link starts after it
MAX_PER_SOURCE = 25  # clips one source may give a pool, so a big pool mixes several videos
WANTED = re.compile(r"cutscenes?|cinematics?|trailer|all scenes", re.I)
SHORT_MIN = 60  # film channels upload 2-5 minute scenes; used when no long source exists


def pick_source(query, min_dur, excluded, channels=None, spent=None, kind="game"):
    """Trusted channels of the pool's kind (`game`: `trusted`, `film`: `film`) first, in list
    order, then a general search without watermark channels.
    Long sources (min_dur) are preferred; failing those, the same order again with short ones.
    `spent` maps video ids to seconds already cut from them: a used-up source is skipped."""
    channels = {"trusted": {}, "film": {}, "watermark": {}, **(channels or {})}
    spent = spent or {}
    # Trusted channels title uploads "<game> Longplay - Full Game Walkthrough": search them by the
    # game's name only and take the longest full-game upload of exactly that game.
    name = " ".join(w for w in query.split() if w.lower() not in GENERIC - {"resident", "evil"})
    cids = [c for c in channels["film" if kind == "film" else "trusted"] if c.startswith("UC")]
    with ThreadPoolExecutor(8) as ex:  # one search per channel, all at once
        found = list(ex.map(lambda c: search(f"https://www.youtube.com/channel/{c}/search?query={urllib.parse.quote(name)}", 20), cids))
    general = None
    banned = set(channels["watermark"]) | set(channels["watermark"].values())
    left = lambda h: (h.get("duration") or 0) * 0.8 - spent.get(h.get("id"), 0) >= 15
    # A Search asking for cutscenes or trailers takes only titles that say so, from any trusted
    # channel and then the general search, before it settles for a longplay or other gameplay.
    want = WANTED.search(query)
    lengths = list(dict.fromkeys([min_dur, min(min_dur, SHORT_MIN)]))
    for only_wanted, least in [(True, n) for n in lengths if want] + [(False, n) for n in lengths]:
        fits = lambda h: left(h) and (not only_wanted or WANTED.search(h.get("title", "")))
        for hits in found:
            for h in [h for h in rank(hits, query, least, excluded, strict=True,
                                      prefer=RAW_DUMP if only_wanted else FULL_GAME) if fits(h)][:2]:
                url = usable({**h, "url": h.get("url") or f"https://www.youtube.com/watch?v={h['id']}"})
                if url:
                    return url
        general = general if general is not None else search(f"ytsearch10:{query}")
        for h in [h for h in rank(general, query, least, excluded, banned, strict=True) if fits(h)][:4]:
            url = usable(h)
            if url:
                return url
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
                          "end": r["end"], "pad": r.get("pad", [0, 0]), "qc": None, "flags": [], "reused": True,
                          "source_url": r.get("url"), "title": r.get("title"), "uploader": r.get("uploader")})
            n -= 1
        rest.append((c, n))
    need = rest
    total = sum(n for _, n in need)
    if total:
        duration = qc.probe(source)["duration"]
        used = [(r["start"], r["end"]) for r in jsonl(library / "library.jsonl") if r.get("url") == url]
        used += [tuple(r["source_range"]) for r in jsonl(project / "media" / "manifest.jsonl")
                 if r.get("source_url") == url and r.get("status") == "accepted"]
        lo, hi = min(skip_head, duration * 0.05), duration - min(skip_tail, duration * 0.1)
        cap = min(len(slots(lo, hi, length, used)), MAX_PER_SOURCE)
        if total > cap:  # a short or capped source: fill whole cues while it lasts; the next auto run takes the rest
            kept, room = [], cap
            for c, n in need:
                if n <= room or not kept:
                    kept.append((c, min(n, room)))
                    room -= kept[-1][1]
            print(f"{pool}: this source gives {cap} of {total} clips; {len(need) - len(kept)} cues left for the next auto run")
            need, total = [(c, n) for c, n in kept if n], cap
        scheduled = starts(lo, hi, total, length, used)
        times = iter(scheduled)
        rng = random.Random(seed)
        lib_dir = library / "youtube" / src_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        for c, n in need:
            for _ in range(n):
                t, tries = next(times), 0
                while True:
                    lib_file = lib_dir / f"{src_id}_{t}-{t + length}.mp4"
                    pad = [min(HANDLE, t), max(0.0, min(HANDLE, duration - t - length))]
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t - pad[0]), "-i", str(source),
                         "-t", str(pad[0] + length + pad[1]), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast", str(lib_file)])
                    m = qc.measure(lib_file)
                    fl = flags_of(m)
                    bad = {"black", "frozen"} & set(fl) or ("watermark?" in fl and tries < 1)
                    if not bad or tries >= 3:
                        break
                    used.append((t, t + length))
                    free = free_times(lo, hi, length, used + [(x, x + length) for x in scheduled]
                                      + [(x["start"], x["end"]) for x in clips])
                    if not free:
                        break
                    lib_file.unlink()
                    t, tries = rng.choice(free), tries + 1
                used.append((t, t + length))
                dst = name()
                shutil.copyfile(lib_file, broll / dst)
                clips.append({"n": len(clips) + 1, "cue_id": c["id"], "line": c["anchor"]["line"],
                              "quote": c["anchor"]["quote"], "match": c["details"].get("match", "subject"),
                              "file": f"B-roll/{dst}", "library_file": lib_file.relative_to(library).as_posix(),
                              "start": t, "end": t + length, "pad": pad, "qc": m, "flags": fl})
    # Pool slugs are short, so two pools (or two runs) can share a name: never reuse a batch's file.
    bdir, batch, k = project / "media" / "pool-batches", f"{pool}-{src_id}", 1
    while (bdir / f"{batch}.json").exists() or (bdir / f"{batch}.committed.json").exists():
        k += 1
        batch = f"{pool}-{src_id}-{k}"
    sheets_dir = project / "media" / "pool-batches" / batch
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips):
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(c.get("pad", [0])[0] + length / 2),
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
    print(f"{batch}: {len(clips)} clips, {len({c['cue_id'] for c in clips})} cues | {' '.join(sheets)}" + (f" | flagged {flagged}" if flagged else ""))
    return state


def auto(a):
    project, library = Path(a.project), Path(a.library)
    cache = cache_dir(project)
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
    channels = load_channels(library)
    in_use = {r["file"] for r in lib_rows if project.name in r.get("used_in", [])}
    in_use.update(r["library_file"] for r in jsonl(project / "media" / "manifest.jsonl")
                  if r.get("status") == "accepted" and r.get("library_file"))
    spent = Counter()  # seconds already cut from each YouTube source, so used-up short ones are skipped
    given = Counter()  # clips each source already gave each of this project's pools
    for r in lib_rows:
        m = re.search(r"[?&]v=([\w-]{11})", str(r.get("url", "")))
        if m:
            spent[m.group(1)] += r["end"] - r["start"]
            if project.name in r.get("used_in", []):
                given[(r.get("subject"), m.group(1))] += 1
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
            kind = footage(chosen[0])
            full = {v for (s, v), n in given.items() if s == subject and n >= MAX_PER_SOURCE}
            url = pick_source(query, 30 if exact else 600, excluded | full, channels, spent, kind)
            if not url and exact:  # lax fallback: the pool's own search
                url = pick_source(subject, 600, excluded | full, channels, spent, kind)
            if not url:
                print(f"{pool}: no source passed the filters for {query!r}; {len(chosen)} cues left")
                continue
            source, src_id, url, info = fetch(url, cache, a.full)
            info["footage"] = kind  # commit --trust files the channel under this kind
        make_batch(project, library, pool, chosen, source, src_id or "library", url, info, a.len,
                   reuse=reuse[:need])
        if src_id:
            excluded.add(src_id)  # Pending cuts aren't in the library index until commit.
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
    cache = cache_dir(project)
    if a.url:
        source, src_id, url, info = fetch(a.url, cache, a.full)
    else:
        source = Path(a.file)
        src_id, url = re.sub(r"\W", "_", source.stem), source.resolve().as_uri()
        info = {"title": source.name, "uploader": None, "license": None}
    info["footage"] = a.footage
    make_batch(project, library, a.pool, [by_id[i] for i in ids], source, src_id, url, info, a.len,
               a.skip_head, a.skip_tail)


def spearfia_cmd():
    if os.environ.get("SPEARFIA_CMD"):  # JSON list, used by the self-test
        return json.loads(os.environ["SPEARFIA_CMD"])
    exe = os.environ.get("SPEARFIA_EXE") or shutil.which("spearfia") or DEFAULT_EXE
    return [exe]


def links_add(project, payload):
    """Call links_add through `spearfia mcp` over stdio; returns the new link ids."""
    payload = {"links": [{**l, "quote": spoken_quote(l["quote"])} for l in payload["links"]]}
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
    pending = [e for e in jsonl(Path(a.project) / "media" / "pool-batches" / "upgrade.jsonl") if not e.get("done")]
    print(f"{filled} of {total} LIVE cues linked; details in production/media-report.md"
          + (f"; {sum(len(e['clips']) for e in pending)} proxy clips from {len(pending)} sources await the upgrade"
             f" (background upgrader {'running' if worker_alive(Path(a.project)) else 'NOT running: run pool.py upgrade'})"
             if pending else ""))


def http_get(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return r.read()


def hls_segments(playlist, base):
    """[(url, t_start, t_end)] from an HLS media playlist."""
    out, t, dur = [], 0.0, None
    for line in playlist.splitlines():
        if line.startswith("#EXTINF:"):
            dur = float(line[8:].split(",")[0])
        elif line and not line.startswith("#") and dur is not None:
            out.append((line if line.startswith("http") else f"{base}/{line}", t, t + dur))
            t, dur = t + dur, None
    return out


def stream_clips(url, clips, cache):
    """Fetch only the ~5 s stream segments that cover each clip (a few MB each) from
    YouTube's HLS stream at up to HQ_MAX, instead of the whole video. YouTube's plain DASH
    URLs need a PO token (403 without one); its HLS segments don't. Returns, per clip, a
    small MPEG-TS or MP4 file and its start time in the source. Raises if there's no HLS stream."""
    meta = json.loads(run(["yt-dlp", "--ignore-config", "--dump-json", "--no-playlist", "-f",
                           f"bv*[height<={HQ_MAX}][protocol^=m3u8]", url]))
    if not str(meta.get("protocol", "")).startswith("m3u8") or not meta.get("url"):
        raise ValueError("no HLS video stream")
    headers = meta.get("http_headers", {})
    playlist = http_get(meta["url"], headers).decode("utf-8", "replace")
    if "#EXT-X-KEY" in playlist:
        raise ValueError("HLS stream is encrypted")
    base = meta["url"].rsplit("/", 1)[0]
    segs = hls_segments(playlist, base)
    if not segs:
        raise ValueError("empty HLS playlist")
    # Fragmented-MP4 streams need their init segment (#EXT-X-MAP) in front of every part.
    m = re.search(r'#EXT-X-MAP:URI="([^"]+)"', playlist)
    init = http_get(m.group(1) if m.group(1).startswith("http") else f"{base}/{m.group(1)}", headers) if m else b""
    ext = "mp4" if init else "ts"
    # The playlist's rounded durations drift (about a second an hour in), so the times come
    # from the segments' own timestamps: the first segment's start is the video's zero.
    first = cache / f"{meta['id']}_zero.part.{ext}"
    first.write_bytes(init + http_get(segs[0][0], headers))
    zero = ts_start(first)
    first.unlink()
    out = []
    for c in clips:
        # one spare segment each side covers the drift
        cover = [x for x in segs if x[2] > c["start"] - 10 and x[1] < c["end"] + 10]
        if not cover:
            raise ValueError(f"clip at {c['start']} s is past the stream's end")
        part = cache / f"{meta['id']}_{c['start']}.part.{ext}"
        part.write_bytes(init + b"".join(http_get(u, headers) for u, _, _ in cover))
        t0 = ts_start(part) - zero
        if not t0 <= c["start"] or t0 + sum(e - b for _, b, e in cover) < c["end"]:
            raise ValueError(f"fetched segments don't cover the clip at {c['start']} s")
        out.append((part, t0))
    return out


def ts_start(path):
    """A media file's first timestamp in seconds."""
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", str(path)]).strip())


def link_entry(c):
    """A links_add entry for a kept clip; with a leading handle it starts where the shot does."""
    pre = c.get("pad", [0, 0])[0]
    return {"line": c["line"], "quote": c["quote"], "media": c["file"], **({"in": f"{pre:.3f}"} if pre else {})}


def recut(entry, hq, project, library, parts=None):
    """Re-cut an upgrade entry's clips from the full-quality source `hq` (or, per clip, from
    `parts`: (file, its start time) as stream_clips returns), with the proxy's crop scaled to
    its size, and replace the project and library copies in place."""
    info = qc.probe(parts[0][0] if parts else hq)
    rows = jsonl(library / "library.jsonl")
    by_file = {r["file"]: r for r in rows}
    for i, c in enumerate(entry["clips"]):
        pre, post = c.get("pad", [0, 0])
        src, seek = (parts[i][0], max(0.0, c["start"] - pre - parts[i][1])) if parts else (hq, c["start"] - pre)
        vf = ""
        cr, (pw, ph) = c.get("crop"), c.get("size") or [None, None]
        if cr and pw and ph:
            sx, sy = info["width"] / pw, info["height"] / ph
            w, h = int(cr["w"] * sx) // 2 * 2, int(cr["h"] * sy) // 2 * 2
            vf = f"crop={w}:{h}:{int(cr['x'] * sx)}:{int(cr['y'] * sy)}"
        lib_file, proj_file = library / c["library_file"], project / c["file"]
        tmp = lib_file.with_name(lib_file.stem + "_hq.mp4")
        # A joined TS part is seconds long: seek after decoding (exact); input seeking on it
        # lands between keyframes and drops frames.
        at = ["-i", str(src), "-ss", f"{seek:.3f}"] if parts else ["-ss", f"{seek:.3f}", "-i", str(src)]
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *at,
             "-t", str(pre + c["end"] - c["start"] + post), *(["-vf", vf] if vf else []), "-an", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast", str(tmp)])
        tmp.replace(lib_file)
        shutil.copyfile(lib_file, proj_file)
        r = by_file.get(c["library_file"])
        if r is not None:
            r.pop("proxy", None)
            r["sha256"] = sha(lib_file)
            r.setdefault("qc", {}).update(width=info["width"], height=info["height"])
    (library / "library.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


HEARTBEAT_STALE = 120  # seconds without a heartbeat before a worker counts as dead


def worker_alive(project):
    hb = project / "media" / "pool-batches" / "upgrade.heartbeat"
    return hb.exists() and time.time() - hb.stat().st_mtime < HEARTBEAT_STALE


def start_worker(project):
    """Start `upgrade --watch` in the background unless one is already running."""
    if worker_alive(project):
        return
    bdir = project / "media" / "pool-batches"
    (bdir / "upgrade.heartbeat").touch()
    log = open(bdir / "upgrade.log", "a", encoding="utf-8")
    # A hidden console, not none: with DETACHED_PROCESS every ffmpeg/yt-dlp it runs opens a window.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "upgrade", "--project", str(project), "--watch"],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    print("started the background upgrader (full-quality downloads); log: media/pool-batches/upgrade.log")


def upgrade(a):
    """Download each queued source at full quality (up to 1440p) and re-cut its kept clips.
    --watch keeps going as commits queue more, and stops after --idle minutes with nothing to do."""
    project = Path(a.project)
    if getattr(a, "watch", False):
        hb, idle_since = project / "media" / "pool-batches" / "upgrade.heartbeat", time.time()
        while time.time() - idle_since < a.idle * 60:
            hb.touch()
            if upgrade_once(project, 1):
                idle_since = time.time()
            else:
                for _ in range(30):  # keep the heartbeat fresh while waiting
                    time.sleep(1)
                hb.touch()
        hb.unlink(missing_ok=True)
        print("upgrader idle; stopping", flush=True)
        return
    upgrade_once(project, a.limit)


def upgrade_once(project, limit):
    """Upgrade up to `limit` queued sources (0: all); returns how many were upgraded."""
    qpath = project / "media" / "pool-batches" / "upgrade.jsonl"
    entries = jsonl(qpath)
    cache = cache_dir(project)
    done = 0
    for e in entries:
        if e.get("done") or (limit and done >= limit):
            continue
        hq, parts = None, None
        try:
            if Path(e["url"]).exists():
                hq = Path(e["url"])
            else:
                try:  # only the segments the clips need; the whole video only if that fails
                    parts = stream_clips(e["url"], e["clips"], cache)
                except (ValueError, OSError, SystemExit, urllib.error.URLError) as err:
                    print(f"segment fetch failed for {e['url']} ({err}); downloading the whole video", flush=True)
                    hq = fetch(e["url"], cache, full=True)[0]
            recut(e, hq, project, Path(e["library"]), parts)
        except (SystemExit, RuntimeError, OSError) as err:
            print(f"upgrade failed for {e['url']}: {err}; it stays queued")
            continue
        e["done"] = True
        done += 1
        for f in ([p for p, _ in parts] if parts else [hq] if hq and str(e["url"]).startswith("http") else []):
            f.unlink(missing_ok=True)
        qpath.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in entries), "utf-8")
        print(f"upgraded {len(e['clips'])} clips from {e['url']}", flush=True)
    left = sum(1 for e in entries if not e.get("done"))
    if done or left:
        print(f"{time.strftime('%H:%M:%S')} {done} sources upgraded; {left} still queued", flush=True)
    return done


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
    for b in a.watermark:  # a watermarked source is rejected whole, and its channel never used again
        drops[b] = "all"
    excluded_path = bdir / "excluded.json"
    excluded = set(json.loads(excluded_path.read_text("utf-8"))) if excluded_path.exists() else set()
    now = datetime.now(timezone.utc).isoformat()
    payload, manifest, kept_total, upgrades = [], [], 0, {}
    for state_path in batches:
        st = json.loads(state_path.read_text("utf-8"))
        if state_path.stem.endswith('.committed'):
            # Recover links after a failed MCP call without cropping or registering clips twice.
            existing = {r['file'] for r in jsonl(project / 'media/manifest.jsonl')}
            for c in st['clips']:
                if not (project / c['file']).exists() or c['file'] in existing:
                    continue
                payload.append(link_entry(c))
                manifest.append({'cue_id': c['cue_id'], 'file': c['file'],
                                 'library_file': c['library_file'], 'source_id': st['source_id'],
                                 'source_url': c.get('source_url') or st['url'], 'title': st['title'],
                                 'uploader': st['uploader'], 'source_range': [c['start'], c['end']],
                                 'risk_class': 'fair-use', 'requested_match': c['match'],
                                 'achieved_match': 'subject (lax exact)' if c['match'] == 'exact' else c['match'],
                                 'qc': c['qc'], 'visual_verdict': 'pass: pool contact sheet',
                                 'status': 'accepted', 'batch': st['batch'], 'reused': bool(c.get('reused'))})
            continue
        library = Path(st["library"])
        drop = drops.get(st["batch"], set())
        if st["batch"] in a.trust + a.watermark and st.get("channel_id"):
            ch = load_channels(library)
            good = "film" if st.get("footage") == "film" else "trusted"
            kind = "watermark" if st["batch"] in a.watermark else good
            ch[kind][st["channel_id"]] = st.get("uploader") or st["channel_id"]
            for other in {"trusted", "film", "watermark"} - {kind}:
                ch[other].pop(st["channel_id"], None)
            save_channels(library, ch)
        if drop == "all":
            excluded.add(st["source_id"])
            drop = {c["n"] for c in st["clips"]}
        lib_rows, reused, rejected = [], set(), set()
        for c in st["clips"]:
            lib_file, proj_file = library / c["library_file"], project / c["file"]
            if c.get("reused"):
                if c["n"] in drop:
                    proj_file.unlink(missing_ok=True)
                    rejected.add(c["library_file"])
                    continue
                reused.add(c["library_file"])
            else:
                row = {"file": c["library_file"], "source": "youtube" if str(st["url"]).startswith("http") else "local",
                       "url": st["url"], "title": st["title"], "uploader": st["uploader"], "start": c["start"],
                       "end": c["end"], "pad": c.get("pad", [0, 0]),
                       "license": st["license"] or "not provided; presumed copyrighted",
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
                             f"crop={cr['w']}:{cr['h']}:{cr['x']}:{cr['y']}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                             "-crf", "18", "-preset", "fast", str(tmpf)])
                        tmpf.replace(f)
                lib_rows.append({**row, "sha256": sha(lib_file), "qc": {"verdict": "pass", "notes": "pool contact sheet"},
                                 "used_in": [project.name], **({"proxy": True} if st.get("proxy") else {})})
                if st.get("proxy"):
                    upgrades.setdefault(st["url"], []).append(
                        {"file": c["file"], "library_file": c["library_file"], "start": c["start"], "end": c["end"],
                         "pad": c.get("pad", [0, 0]), "crop": cr, "size": [(c["qc"] or {}).get("width"), (c["qc"] or {}).get("height")]})
            manifest.append({"cue_id": c["cue_id"], "file": c["file"], "file_sha256": sha(proj_file),
                             "library_file": c["library_file"], "source_id": st["source_id"],
                             "source_url": c.get("source_url") or st["url"], "title": c.get("title") or st["title"],
                             "uploader": c.get("uploader") or st["uploader"], "source_range": [c["start"], c["end"]],
                             "risk_class": "fair-use", "requested_match": c["match"], "achieved_match":
                             c["match"] if c["match"] != "exact" else "subject (lax exact)",
                             "qc": c["qc"], "visual_verdict": "pass: pool contact sheet", "status": "accepted",
                             "batch": st["batch"], "reused": bool(c.get("reused"))})
            payload.append(link_entry(c))
            kept_total += 1
        if reused or rejected:  # mark reused library clips as used here; dropped ones as failed so they aren't offered again
            all_rows = jsonl(library / "library.jsonl")
            for r in all_rows:
                if r["file"] in reused and project.name not in r.setdefault("used_in", []):
                    r["used_in"].append(project.name)
                if r["file"] in rejected:
                    r["qc"] = {**(r.get("qc") or {}), "verdict": "fail", "reason": "dropped in review"}
            (library / "library.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows), "utf-8")
        append(library / "library.jsonl", lib_rows)
        if not a.keep_cache and st.get("source") and str(st["url"]).startswith("http"):
            Path(st["source"]).unlink(missing_ok=True)
        state_path.replace(state_path.with_suffix(".committed.json"))
    excluded_path.parent.mkdir(parents=True, exist_ok=True)
    excluded_path.write_text(json.dumps(sorted(excluded)), "utf-8")
    if upgrades:
        append(bdir / "upgrade.jsonl", [{"url": u, "library": str(library), "clips": cs, "done": False}
                                        for u, cs in upgrades.items()])
        print(f"queued {sum(len(cs) for cs in upgrades.values())} proxy clips for the full-quality upgrade")
        if not a.no_link:
            start_worker(project)
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
    first = {'id': 'first', 'title': 'John Wick (2014) fight scene', 'duration': 180}
    sequel = {'id': 'sequel', 'title': 'John Wick Chapter 3 fight scene', 'duration': 900}
    assert rank([sequel, first], 'John Wick fight scene', 60, set()) == [first]
    assert rank([sequel], 'John Wick fight scene', 60, set()) == []
    assert rank([sequel], 'John Wick fight scenes', 60, set()) == []
    online = {'id': 'online', 'title': 'GTA 5 Cayo Perico All Infiltrations and Exfil Cutscenes', 'duration': 180}
    assert rank([online], 'GTA 5 all cutscenes', 60, set()) == []
    assert rank([online], 'GTA 5 Cayo Perico cutscenes', 60, set()) == [online]
    contract = {'id': 'contract', 'title': 'GTA 5 - The Contract Heist Solo - Full Gameplay', 'duration': 180}
    assert rank([contract], 'GTA 5 all cutscenes', 60, set()) == []
    fraction = {'id': 'fraction', 'title': 'GTA V - All Cutscenes 3/3 (Game Movie)', 'duration': 180}
    assert rank([fraction], 'GTA 3 all cutscenes', 60, set(), strict=True) == []
    roman = {'id': 'roman', 'title': 'Grand Theft Auto III All Cutscenes', 'duration': 180}
    assert rank([roman], 'GTA 3 all cutscenes', 60, set(), strict=True) == [roman]
    assert spoken_quote('VO: [excited] Could John Wick?') == 'Could John Wick?'
    assert spoken_quote('Plain speech.') == 'Plain speech.'
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
        # Each clip carries 2.5 s handles around its 5 s shot, and its link starts at the shot.
        assert all(c["pad"] == [HANDLE, HANDLE] for c in st["clips"]), [c["pad"] for c in st["clips"]]
        assert abs(qc.probe(proj / st["clips"][0]["file"])["duration"] - 10) < 0.2
        assert link_entry(st["clips"][0])["in"] == "2.500"
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
        # Dropping a reused clip fails it in the library, so it isn't offered again.
        proj3 = tmp / "proj-drop"
        (proj3 / "visuals").mkdir(parents=True)
        (proj3 / "visuals" / "visuals.md").write_text("## X - one\n" + cue("d1", 3, 20) + "\n", "utf-8")
        main(["auto", "--project", str(proj3), "--library", str(lib)])
        st3 = json.loads((proj3 / "media/pool-batches/game-a-library.json").read_text("utf-8"))
        main(["commit", "--project", str(proj3), "--drop", "game-a-library:1"])
        failed = {r["file"]: r["qc"]["verdict"] for r in jsonl(lib / "library.jsonl")}
        assert failed[st3["clips"][0]["library_file"]] == "fail", failed
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
        bp = proj / "media/pool-batches/T-src-2.json"
        bp.write_text(json.dumps({**json.loads(bp.read_text("utf-8")), "channel_id": "UCbad", "uploader": "Bad"}), "utf-8")
        main(["commit", *base, "--watermark", "T-src-2", "--no-link"])
        assert json.loads((proj / "media/pool-batches/excluded.json").read_text()) == ["src"]
        assert load_channels(lib)["watermark"] == {"UCbad": "Bad"}, load_channels(lib)
        # rank(): watermark channels out, the right game, no DLC, the longest compilation first.
        hits = [{"id": "a", "title": "Alpha All Cutscenes", "duration": 3600, "channel_id": "UCbad"},
                {"id": "b", "title": "Alpha All Cutscenes Movie", "duration": 7200, "channel_id": "UCok"},
                {"id": "c", "title": "Alpha DLC All Cutscenes", "duration": 9000, "channel_id": "UCok"},
                {"id": "d", "title": "Beta All Cutscenes", "duration": 9900, "channel_id": "UCok"},
                {"id": "e", "title": "Alpha Walkthrough", "duration": 50000, "channel_id": "UCok"},
                {"id": "f", "title": "Alpha Boss Cutscene", "duration": 900, "channel_id": "UCok"}]
        assert [h["id"] for h in rank(hits, "Alpha all cutscenes", 600, set(), {"UCbad"})] == ["b", "f", "e"]
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
        # upgrade: a clip cut from a 640x360 proxy is re-cut from the 1280x720 source.
        small = tmp / "small.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vf", "scale=640:360",
             "-c:v", "libx264", "-preset", "ultrafast", str(small)])
        up = tmp / "up"; (up / "B-roll").mkdir(parents=True); ulib = tmp / "ulib"; (ulib / "y").mkdir(parents=True)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "10", "-i", str(small), "-t", "5", "-an",
             "-c:v", "libx264", "-preset", "ultrafast", str(ulib / "y" / "c.mp4")])
        shutil.copyfile(ulib / "y" / "c.mp4", up / "B-roll" / "c.mp4")
        append(ulib / "library.jsonl", [{"file": "y/c.mp4", "proxy": True, "qc": {"width": 640, "height": 360}}])
        recut({"clips": [{"file": "B-roll/c.mp4", "library_file": "y/c.mp4", "start": 10, "end": 15,
                          "crop": {"w": 640, "h": 300, "x": 0, "y": 30}, "size": [640, 360]}]}, src, up, ulib)
        got = qc.probe(up / "B-roll" / "c.mp4")
        assert (got["width"], got["height"]) == (1280, 600), got
        assert "proxy" not in jsonl(ulib / "library.jsonl")[0], jsonl(ulib / "library.jsonl")
        assert slug("Resident Evil 2 remake Mr. X (Tyrant)") == "resident-evil-2-rema"
        assert REJECT_WORDS.search("Mr X reaction") and not REJECT_WORDS.search(
            NO_COMMENTARY.sub("", "RE2 all cutscenes no commentary"))
        # Clip starts never overlap; a short source fills whole cues and leaves the rest.
        assert slots(0, 30, 5, [(10, 15)]) == [0, 5, 15, 20]
        assert starts(0, 30, 3, 5, []) == [0, 10, 20]
        short = tmp / "short.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "testsrc2=size=640x360:rate=24:duration=12", "-c:v", "libx264", "-preset", "ultrafast", str(short)])
        ps = tmp / "proj-short"
        (ps / "visuals").mkdir(parents=True)
        (ps / "visuals" / "visuals.md").write_text("## A - one\n" + cue("c1", 5, 10) + "\n\n## B - two\n" + cue("c2", 7, 30) + "\n", "utf-8")
        main(["cut", "--project", str(ps), "--pool", "S", "--cues", "c1,c2", "--file", str(short), "--library", str(lib),
              "--skip-head", "0", "--skip-tail", "0"])
        st5 = json.loads((ps / "media/pool-batches/S-short.json").read_text("utf-8"))
        assert [c["cue_id"] for c in st5["clips"]] == ["c1"], st5["clips"]
        # Exhausted recut ranges retain the last flagged clip for visual rejection.
        black = tmp / 'black.mp4'
        run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
             'color=black:s=640x360:d=6', '-c:v', 'libx264', str(black)])
        state = make_batch(ps, lib, 'black', all_cues(ps)[:1], black, 'black',
                           black.as_uri(), {'title': 'black'}, skip_head=0, skip_tail=0)
        assert state['clips'] and all((ps / c['file']).exists() for c in state['clips'])
        # Trusted channels are searched together but preferred in list order; long sources first,
        # short ones (film scenes) only when no long one is left; used-up sources are skipped.
        fake = {"UCa": [{"id": "aaaaaaaaaaa", "title": "Game A scene", "duration": 150}],
                "UCb": [{"id": "bbbbbbbbbbb", "title": "Game A full game", "duration": 900}]}
        real = search, usable
        globals()["search"] = lambda t, n=10: next((v for k, v in fake.items() if k in t), [])
        globals()["usable"] = lambda h: h["url"]
        try:
            ch = {"trusted": {"UCa": "A", "UCb": "B"}, "watermark": {}}
            assert pick_source("game a", 600, set(), ch).endswith("bbbbbbbbbbb")
            assert pick_source("game a", 600, set(), ch, {"bbbbbbbbbbb": 900}).endswith("aaaaaaaaaaa")
            assert pick_source("game a", 600, set(), ch, {"bbbbbbbbbbb": 900, "aaaaaaaaaaa": 120}) is None
            # A film pool searches only the film channels.
            fake["UCf"] = [{"id": "fffffffffff", "title": "Game A fight scene", "duration": 200}]
            ch["film"] = {"UCf": "F"}
            assert pick_source("game a", 600, set(), ch, kind="film").endswith("fffffffffff")
            assert footage({"details": {"Footage": "Film"}}) == "film" and footage({"details": {}}) == "game"
        finally:
            globals()["search"], globals()["usable"] = real
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
    au.add_argument("--full", action="store_true", help="download full quality now instead of a review proxy")
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
    c.add_argument("--full", action="store_true", help="download full quality now instead of a review proxy")
    c.add_argument("--footage", choices=["game", "film"], default="game", help="film: commit --trust files the channel as a film channel")
    m = sub.add_parser("commit")
    m.add_argument("--project", required=True)
    m.add_argument("--batch", default="", help="only this batch (default: every pending batch)")
    m.add_argument("--drop", action="append", default=[], help="BATCH:N,N or BATCH:all; repeatable")
    m.add_argument("--keep-cache", action="store_true")
    m.add_argument("--trust", action="append", default=[], help="BATCH: its channel has no watermark; search it first next time")
    m.add_argument("--watermark", action="append", default=[], help="BATCH: its channel watermarks; reject the source, never use the channel")
    m.add_argument("--no-link", action="store_true", help="print the links_add payload instead of linking")
    s = sub.add_parser("status")
    s.add_argument("--project", required=True)
    u = sub.add_parser("upgrade", help="re-cut kept proxy clips from the full-quality source")
    u.add_argument("--project", required=True)
    u.add_argument("--limit", type=int, default=0, help="sources per run (0: all)")
    u.add_argument("--watch", action="store_true", help="keep upgrading as commits queue more (commit starts this itself)")
    u.add_argument("--idle", type=float, default=20, help="--watch: stop after this many minutes with nothing queued")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    {"auto": auto, "cut": cut, "commit": commit, "status": status, "upgrade": upgrade}[a.cmd](a)


if __name__ == "__main__":
    main(sys.argv[1:])
