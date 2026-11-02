# SPDX-License-Identifier: MIT OR Apache-2.0
"""Checklist and indexing: python jev.py --project <demo-folder> needs|index|status."""
import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


URL = re.compile(r"(?:https?://|(?:www\.)?(?:youtube\.com|youtu\.be)/)[^\s<>`]+", re.I)
NAMES = re.compile(r"\b(?:John|Wick|GTA|Maverick|Rhino|NOOSE|Charon|Caine|Kirill|Aurelio|Leonida)\b", re.I)
SOURCE_GROUPS = {
    "wick1": "John Wick 1", "wick2": "John Wick 2", "wick3": "John Wick 3", "wick4": "John Wick 4",
    "gta3": "GTA 3", "gta4": "GTA 4", "gta5": "GTA 5", "gta6": "GTA 6",
    "gtasa": "San Andreas", "gtavc": "Vice City",
}


def require_legacy(project):
    if (Path(project)/'media/jev/script-first/approval.json').exists():
        raise ValueError('Approved script-first beats replace the old cue plan; use prepare-beats/general-pools. Legacy index/assign/build are disabled.')


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
                raise ValueError(f"URL at line {line_number} is outside a recognized source group or need heading")
            validate_url(url)
            if url not in sources[current]:
                sources[current].append(url)
    return sources


def paste_targets(needs):
    targets = {"group-"+group: [n["id"] for n in needs if n["source_group"] == group
               and not n.get("review_only") and not n.get("manual")] for group in SOURCE_GROUPS}
    return targets | {n["id"]: [] if n.get("manual") else [n["id"]] for n in needs}


def expand_sources(needs, sources):
    """Resolve paste boxes to questions, keeping group/individual URL placement intact."""
    targets = paste_targets(needs)
    expanded = {n["id"]: [] for n in needs}
    for key, urls in sources.items():
        if key not in targets:
            raise ValueError("Stored URLs reference an unknown source group or need")
        if urls and not targets[key]:
            raise ValueError(f"{key} is handled by hand; do not paste search URLs under it")
        if key == "grieving-man" and len(set(urls)) > 1:
            raise ValueError("The optional grieving-man control takes one John Wick 1 URL")
        for url in urls:
            validate_url(url)
            for need_id in targets[key]:
                if url not in expanded[need_id]:
                    expanded[need_id].append(url)
    return expanded


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
        if need.get("source_group") not in SOURCE_GROUPS:
            raise ValueError("Every need requires a known film/game source group")
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
        if need["cues"] and not any(cues[key]["match"] == "exact" for key in need["cues"]) and not need["fallback"] and not need.get("generic"):
            raise ValueError("Non-exact needs require a broader fallback or must be a broad root")
        assigned.extend(need["cues"])
        chain = {need["id"]}
        fallback = need["fallback"]
        while fallback:
            if fallback not in by_id or fallback in chain:
                raise ValueError("Fallbacks must exist and must not form a cycle")
            if by_id[fallback]["source_group"] != need["source_group"] or by_id[fallback].get("manual") or by_id[fallback].get("review_only"):
                raise ValueError("Fallback must be a searchable need from the same film/game")
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
        "Paste YouTube video URLs into the source-group boxes first. Each URL gets all that film/game's search questions. Individual need boxes below are optional additions. Plain lines, bullets and Markdown links work; the heading supplies the tag.", "",
        "Seconds are estimates from narration words at 2.6 words/sec; precise VO timing comes later. All search rounds use context 32,768, plain visual descriptions and black-frame filtering. No URLs have been selected for you.", "",
        "These files prepare the demo workspace only. The approved original remains unchanged; the full project copy and indexing wait for Stage 3.", "",
        "Exact scenes stay strict: no broader fallback; any unfilled exact requirement must be listed in the coverage report. The six-slot HUD is handled by hand and is excluded from automatic questions. The grieving-man control is optional and has its own single-URL box.", ""]
    targets = paste_targets(needs)
    for group, label in SOURCE_GROUPS.items():
        key = "group-"+group
        lines += [f"## {key}: {label}", "",
                  "Every URL here gets these questions: "+", ".join("`"+key+"`" for key in targets[key])+".", ""]
        if group == "gta6":
            lines += ["Official promotional footage only. `gta6-six-slot-hud` is handled by hand; it is not an automatic question.", ""]
        if group == "wick1":
            lines += ["The optional grieving-man control is separate; a group URL does not enable it.", ""]
        lines += ["```text", *(sources[key] or ["Paste URLs here, one per line."]), "```", ""]
    controls = [n for n in ordered if n.get("review_only")]
    lines += ["## Optional review control", "",
              "One John Wick 1 URL is enough for the grieving-man check. Leave its box empty to skip it; it creates no narration demand.", ""]
    for index, need in enumerate([*controls, *[n for n in ordered if not n.get("review_only")]]):
        if index == len(controls):
            lines += ["## Optional individual needs", "", "Use these boxes only for URLs that should answer a particular need. Group URLs already apply and are not repeated here.", ""]
        cue_rows = [cues[key] for key in need["cues"]]
        lines += [f"### {need['id']}: {need['label']} (~{math.ceil(demand[need['id']])} s, {len(cue_rows)} {'cue' if len(cue_rows) == 1 else 'cues'})", "",
                  "Source scope: "+need["source_scope"], "", "Find: "+need["query"], ""]
        if need.get("review_only"):
            lines += ["**Optional review control only — no narration demand.** When enabled, include it in the Stage 3 hard-need check, not on the timeline.", ""]
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
        elif need.get("generic") and not exact:
            lines += ["Broadest existing fallback root for this film/game; no further fallback.", ""]
        lines += ["Confirmation target: "+need["confirm"]["right"], ""]
        if need.get("manual"):
            lines += ["**Handled by hand — no search URLs required.** Keep the exact scene in coverage until manually supplied and verified.", ""]
        else:
            lines += ["```text", *(sources[need["id"]] or ["Paste an optional URL here." if need.get("review_only") else "Paste optional URLs here, one per line."]), "```", ""]
    return "\n".join(lines).rstrip()+"\n"


def write_checklist(project):
    if (project/'media/jev/script-first/approval.json').exists():
        from script_first import prepare
        result=prepare(project)
        return project/'production/media-checklist.md',result['questions'],result['pasted_url_entries']
    folder = project / "media" / "jev"
    inputs = json.loads((folder/"input-cues.json").read_text(encoding="utf-8"))
    if project.resolve() == Path(inputs["source_project"]).resolve():
        raise ValueError("The approved original is read-only; use the demo staging folder")
    needs = json.loads((folder/"needs.json").read_text(encoding="utf-8"))
    validate_needs(needs, inputs)
    targets = paste_targets(needs)
    checklist = project/"production"/"media-checklist.md"
    source_file = folder/"sources.json"
    if checklist.exists():
        sources = parse_checklist(checklist.read_text(encoding="utf-8"), targets)
    elif source_file.exists():
        stored = json.loads(source_file.read_text(encoding="utf-8"))
        if any(key not in targets and value for key, value in stored.items()):
            raise ValueError("Stored URLs reference an unknown source group or need; resolve it before regenerating")
        sources = {key: list(dict.fromkeys(validate_url(url) for url in stored.get(key, []))) for key in targets}
    else:
        sources = {key: [] for key in targets}
    expand_sources(needs, sources)
    rendered = render_checklist(needs, inputs, sources)
    checklist.parent.mkdir(parents=True, exist_ok=True)
    for path, text in [(source_file, json.dumps(sources, indent=2)+"\n"), (checklist, rendered)]:
        temporary = path.with_suffix(path.suffix+".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return checklist, len(needs), sum(len(urls) for urls in sources.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["needs", "index", "status", "assign", "build", "prepare-beats", "general-pools", "specific-queries", "script-timeline", "fill", "swap", "stage5-test", "edit-prepare", "edit-preview", "finalize"])
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--review",type=Path)
    parser.add_argument("--at")
    parser.add_argument("--need")
    parser.add_argument("--query")
    parser.add_argument("--group",choices=list(SOURCE_GROUPS))
    parser.add_argument('--editing-recipe',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--section',default='Star 4')
    args = parser.parse_args()
    if args.command == 'edit-prepare':
        if not args.review or not args.out: parser.error('edit-prepare requires --review and a fresh --out')
        from editing_recipe import prepare
        result=prepare(args.project,args.review,args.out,args.section)
        print(json.dumps(dict(windows=len(result['windows']),recipe=str(args.out/'editing-recipe.json'))))
    elif args.command == 'edit-preview':
        if not args.editing_recipe: parser.error('edit-preview requires --editing-recipe')
        from editing_recipe import preview
        result=preview(args.editing_recipe.parent)
        print(json.dumps(dict(model_calls=result['model_calls'],applied=result['applied'],gate=result['gate'])))
    elif args.command == 'finalize' and args.editing_recipe:
        from editing_recipe import finalize
        print(finalize(args.editing_recipe))
    elif args.command == 'prepare-beats':
        from script_first import prepare
        prepare(args.project.resolve())
    elif args.command == 'general-pools':
        from script_text_screens import scan_pools
        scan_pools(args.project.resolve())
    elif args.command == 'specific-queries':
        from script_queries import run
        run(args.project.resolve())
    elif args.command == 'script-timeline':
        from script_stage4 import run
        run(args.project.resolve())
    elif args.command in {'fill','swap'}:
        if not args.review or not args.at:parser.error('fill/swap require --review and --at')
        from stage5_edit import edit
        print(json.dumps(edit(args.project.resolve(),args.review.resolve(),args.command,args.at,need=args.need,query=args.query,group=args.group),indent=2))
    elif args.command=='stage5-test':
        if not args.review:parser.error('stage5-test requires the saved edited --review')
        from stage5_check import run
        run(args.project.resolve(),args.review.resolve())
    elif args.command=='finalize':
        if not args.review:parser.error('finalize requires the creator-edited --review')
        from stage6_finalize import run
        run(args.project.resolve(),args.review.resolve())
    elif args.command == "needs":
        path, count, urls = write_checklist(args.project)
        label='questions' if (args.project/'media/jev/script-first/approval.json').exists() else 'needs'
        print(f"Ready: {count} {label}, {urls} pasted URL entries. {path}")
    elif args.command == "index":
        from stage3_sources import run as sources
        if (args.project/'media'/'jev'/'resume-policy.json').exists():
            from stage3_resume import run as index
        else:
            from stage3_index import run as index
        sources(args.project)
        index(args.project)
    elif args.command == "assign":
        from stage4_assign import Assignment,cut_masters
        assignment=Assignment(args.project.resolve())
        if assignment.project==Path(assignment.inputs['source_project']).resolve():
            raise ValueError('Original project is read-only')
        assignment.prepare();assignment.build_slots()
        result=assignment.allocate()
        cut_masters(assignment.project,result,assignment.videos)
        print(f"Assigned {sum(bool(s['top']) for s in result['slots'])}/{len(result['slots'])} slots.")
    elif args.command == "build":
        from stage4_build import build
        build(args.project.resolve())
    else:
        choices=['media/jev/script-first/stage6/run.json','media/jev/script-first/stage5/run.json','media/jev/script-first/stage4-run.json','media/jev/script-first/query-run.json','media/jev/script-first/summary.json'] if (args.project/'media/jev/script-first/approval.json').exists() else ['media/jev/index-status.json']
        status=next((args.project/p for p in choices if (args.project/p).exists()),args.project/choices[0])
        print(status.read_text(encoding="utf-8") if status.exists() else "Indexing has not started.")
