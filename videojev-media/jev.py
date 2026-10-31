# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stage 2 checklist: python jev.py --project <demo-folder> needs."""
import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


URL = re.compile(r"(?:https?://|(?:www\.)?(?:youtube\.com|youtu\.be)/)[^\s<>`]+", re.I)
NAMES = re.compile(r"\b(?:John|Wick|GTA|Maverick|Rhino|NOOSE|Charon|Caine|Kirill|Aurelio|Leonida)\b", re.I)


def validate_url(url):
    parsed = urlsplit(url if "://" in url else "https://"+url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("Expected a plain YouTube video URL")
    if host in {"youtu.be", "www.youtu.be"}:
        video = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        parts = parsed.path.strip("/").split("/")
        video = parse_qs(parsed.query).get("v", [""])[0] if parsed.path == "/watch" else (
            parts[1] if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"} else "")
    else:
        raise ValueError("Checklist entries must be YouTube video URLs")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        raise ValueError("Expected a YouTube video link, not a playlist or channel")
    return url


def parse_checklist(text, need_ids):
    sources = {key: [] for key in need_ids}
    current = None
    for line_number, line in enumerate(text.splitlines(), 1):
        heading = re.match(r"^\s*#{1,6}\s+(.+)", line)
        if heading:
            key = heading[1].split(":", 1)[0].strip()
            current = key if key in sources else None
        for match in URL.finditer(line):
            url = match.group().rstrip(".,;!?)\"']}")
            if current is None:
                raise ValueError(f"URL at line {line_number} is outside a recognized need heading")
            validate_url(url)
            if url not in sources[current]:
                sources[current].append(url)
    return sources


def validate_needs(needs, inputs):
    cues = {c["id"]: c for c in inputs["cues"]}
    ids = [need["id"] for need in needs]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) for key in ids):
        raise ValueError("Need IDs must be unique kebab-case strings")
    assigned = []
    by_id = {need["id"]: need for need in needs}
    for need in needs:
        if not all(isinstance(value, list) for value in [need["cues"], need.get("variants", []), need["confirm"]["wrong"]]):
            raise ValueError("Cue IDs, variants and distractors must be lists")
        if not need.get("label") or not need.get("source_scope"):
            raise ValueError("Every need requires a label and source scope")
        for query in [need["query"], *need.get("variants", [])]:
            if not query.strip() or "<|" in query or NAMES.search(query):
                raise ValueError(f"Use plain, name-free visual descriptions: {need['id']}")
        choices = [need["confirm"]["right"], *need["confirm"]["wrong"]]
        if not need["confirm"]["question"].strip() or len(choices) < 3 or any(not c.strip() for c in choices):
            raise ValueError("Confirmation requires a question, target and at least two distractors")
        if len({c.casefold().strip() for c in choices}) != len(choices):
            raise ValueError("Confirmation choices must be distinct")
        if not need["cues"] and not need.get("review_only"):
            raise ValueError("Only review controls may have no narration cues")
        if need.get("review_only") and need["cues"]:
            raise ValueError("A review-only control must not invent narration demand")
        if any(key not in cues for key in need["cues"]):
            raise ValueError("Unknown or non-footage cue ID")
        subjects = {cues[key]["subject"] for key in need["cues"]}
        if len(subjects) > 1:
            raise ValueError(f"Keep distinct approved film/game sources separate: {need['id']}")
        if any(cues[key]["match"] == "exact" for key in need["cues"]) and need["fallback"]:
            raise ValueError("Exact evidence must not silently fall back to a broader need")
        assigned.extend(need["cues"])
        chain = {need["id"]}
        fallback = need["fallback"]
        while fallback:
            if fallback not in by_id or fallback in chain:
                raise ValueError("Fallbacks must exist and must not form a cycle")
            target_subjects = {cues[key]["subject"] for key in by_id[fallback]["cues"]}
            if subjects != target_subjects:
                raise ValueError("Fallback must retain the approved film/game source")
            chain.add(fallback)
            fallback = by_id[fallback]["fallback"]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(cues):
        raise ValueError("Every LIVE cue must appear exactly once")
    return cues


def render_checklist(needs, inputs, sources):
    cues = validate_needs(needs, inputs)
    demand = {n["id"]: sum(cues[key]["seconds_estimate"] for key in n["cues"]) for n in needs}
    ordered = sorted(needs, key=lambda n: (-demand[n["id"]], n["id"]))
    lines = ["# VideoJev media checklist", "",
        "Paste one or more YouTube video URLs under each need heading. Plain lines, bullets and Markdown links work; the heading supplies the tag. The same video may serve several needs.", "",
        "Seconds are estimates from narration words at 2.6 words/sec; precise VO timing comes later. All search rounds use context 32,768, plain visual descriptions and black-frame filtering. No URLs have been selected for you.", "",
        "These files prepare the demo workspace only. The approved original remains unchanged; the full project copy and indexing wait for Stage 3.", ""]
    for need in ordered:
        cue_rows = [cues[key] for key in need["cues"]]
        lines += [f"## {need['id']}: {need['label']} (~{math.ceil(demand[need['id']])} s, {len(cue_rows)} {'cue' if len(cue_rows) == 1 else 'cues'})", "",
                  "Source scope: "+need["source_scope"], "", "Find: "+need["query"], ""]
        if need.get("review_only"):
            lines += ["**Review control only — no narration demand.** Include it in the Stage 3 hard-need check, not on the timeline.", ""]
        if need.get("hard"):
            lines += ["Stage 3 hard need: show the multiple-choice answers, probabilities and pass/fail beside the review images.", ""]
        if cue_rows:
            quote = cue_rows[0]["quote"]
            if len(quote) > 220:
                quote = quote[:217].rsplit(" ", 1)[0]+"…"
            lines += ["Example line: “"+quote+"”", ""]
        exact = list(dict.fromkeys(c["visual"] for c in cue_rows if c["match"] == "exact"))
        for visual in exact:
            lines += ["Required scene: "+visual, ""]
        if need["fallback"]:
            lines += ["Broader fallback if supply runs out: `"+need["fallback"]+"` (reported explicitly in coverage).", ""]
        lines += ["Confirmation target: "+need["confirm"]["right"], "",
                  *["- "+url for url in sources[need["id"]]]]
        if not sources[need["id"]]:
            lines.append("<!-- Paste YouTube video URLs here. -->")
        lines.append("")
    return "\n".join(lines).rstrip()+"\n"


def write_checklist(project):
    folder = project / "media" / "jev"
    inputs = json.loads((folder/"input-cues.json").read_text(encoding="utf-8"))
    if project.resolve() == Path(inputs["source_project"]).resolve():
        raise ValueError("The approved original is read-only; use the demo staging folder")
    needs = json.loads((folder/"needs.json").read_text(encoding="utf-8"))
    validate_needs(needs, inputs)
    checklist = project/"production"/"media-checklist.md"
    source_file = folder/"sources.json"
    if checklist.exists():
        sources = parse_checklist(checklist.read_text(encoding="utf-8"), [n["id"] for n in needs])
    elif source_file.exists():
        stored = json.loads(source_file.read_text(encoding="utf-8"))
        if any(key not in {n["id"] for n in needs} and value for key, value in stored.items()):
            raise ValueError("Stored URLs reference an unknown need; resolve it before regenerating")
        sources = {n["id"]: list(dict.fromkeys(validate_url(url) for url in stored.get(n["id"], []))) for n in needs}
    else:
        sources = {n["id"]: [] for n in needs}
    rendered = render_checklist(needs, inputs, sources)
    checklist.parent.mkdir(parents=True, exist_ok=True)
    for path, text in [(source_file, json.dumps(sources, indent=2)+"\n"), (checklist, rendered)]:
        temporary = path.with_suffix(path.suffix+".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return checklist, len(needs), sum(len(urls) for urls in sources.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["needs"])
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    path, count, urls = write_checklist(args.project)
    print(f"Ready: {count} needs, {urls} pasted URL entries. {path}")
