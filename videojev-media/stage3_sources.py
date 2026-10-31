# SPDX-License-Identifier: MIT OR Apache-2.0
"""Prepare the protected demo copy and download the creator's source proxies."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jev import expand_sources, parse_checklist, paste_targets, validate_needs

sys.path.insert(0, str(Path(__file__).parents[1]/"media-search"/"scripts"))
import pool
import qc

PROXY_FORMAT = "bv*[height=480]/bv*[height<=480][height>=360]"


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    temporary.replace(path)


def video_id(url):
    parts = urlsplit(url if "://" in url else "https://"+url)
    return parse_qs(parts.query)["v"][0] if parts.path == "/watch" else parts.path.rstrip("/").split("/")[-1]


def prepare_project(project):
    folder = project/"media"/"jev"
    inputs = json.loads((folder/"input-cues.json").read_text(encoding="utf-8"))
    original = Path(inputs["source_project"])
    if project.resolve() == original.resolve():
        raise ValueError("Never write into the approved original")
    for relative, key in [("script/script.md", "script_sha256"), ("visuals/visuals.md", "visuals_sha256")]:
        if hashlib.sha256((original/relative).read_bytes()).hexdigest() != inputs[key]:
            raise ValueError("Approved source changed since the needs were frozen")
    checklist = project/"production"/"media-checklist.md"
    submitted = checklist.read_bytes()
    needs = json.loads((folder/"needs.json").read_text(encoding="utf-8"))
    validate_needs(needs, inputs)
    entries = parse_checklist(submitted.decode("utf-8"), paste_targets(needs))
    expanded = expand_sources(needs, entries)
    if not (folder/"copy-report.json").exists():
        copied = 0
        for source in original.rglob("*"):
            relative = source.relative_to(original)
            if not source.is_file() or relative.parts[0] in {"B-roll", ".git"} or source.name == ".spearfia-edit.lock":
                continue
            if relative.parts[:2] == ("media", "jev") or relative.as_posix() == "production/media-checklist.md":
                continue
            target = project/relative
            if target.exists():
                raise ValueError(f"Unexpected existing copy target; refusing to overwrite: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        original_links = json.loads((original/"links.json").read_text(encoding="utf-8"))
        kept = [link for link in original_links["links"] if link.get("media", {}).get("path", "").replace("\\", "/").split("/")[0] != "B-roll"]
        save_json(project/"links.json", {**original_links, "links": kept})
        save_json(folder/"copy-report.json", dict(original=str(original), copied_files=copied,
            old_broll_links_removed=len(original_links["links"])-len(kept), links_retained=len(kept),
            checklist_sha256=hashlib.sha256(submitted).hexdigest(), created=time.time()))
    if checklist.read_bytes() != submitted:
        raise RuntimeError("Checklist was changed during the project copy")
    save_json(folder/"sources.json", entries)
    archive = folder/"checklist-submitted.md"
    if not archive.exists():
        archive.write_bytes(submitted)
    videos = {}
    by_need = {n["id"]: n for n in needs}
    for need_id, urls in expanded.items():
        for url in urls:
            key = video_id(url)
            video = videos.setdefault(key, dict(id=key, url=f"https://www.youtube.com/watch?v={key}", submitted_urls=[], needs=[], groups=[]))
            if url not in video["submitted_urls"]:
                video["submitted_urls"].append(url)
            if need_id not in video["needs"]:
                video["needs"].append(need_id)
            group = by_need[need_id]["source_group"]
            if group not in video["groups"]:
                video["groups"].append(group)
    save_json(folder/"source-list.json", list(videos.values()))
    return list(videos.values())


def command(args, timeout):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:].strip())
    return result.stdout


def download(video, cache, folder):
    output = folder/"downloads"/(video["id"]+".json")
    if output.exists():
        prior = json.loads(output.read_text(encoding="utf-8"))
        if prior["status"] == "ready" and Path(prior["path"]).exists():
            prior.update(video)
            save_json(output, prior)
            return prior
    started = time.perf_counter()
    row = dict(video, status="downloading")
    save_json(output, row)
    try:
        common = ["yt-dlp", "--ignore-config", "--no-playlist", "--socket-timeout", "30", "--retries", "1", "--fragment-retries", "1"]
        metadata = json.loads(command([*common, "--dump-single-json", "--skip-download", "-f", PROXY_FORMAT, video["url"]], 180))
        row.update({key: metadata.get(key) for key in ["title", "uploader", "channel_id", "duration", "age_limit", "webpage_url"]})
        if metadata.get("age_limit", 0) >= 18:
            raise RuntimeError("Age-restricted source; no cookies or bypass attempted")
        target = cache/(video["id"]+".proxy.mp4")
        if not target.exists():
            command([*common, "--no-progress", "--abort-on-unavailable-fragments", "--concurrent-fragments", "4",
                "-f", PROXY_FORMAT, "--remux-video", "mp4", "-o", str(cache/(video["id"]+".proxy.%(ext)s")), video["url"]], 7200)
        probe = qc.probe(target)
        if probe["height"] < 360 or probe["duration"] <= 0:
            raise RuntimeError("Proxy does not meet the 360p minimum or has no duration")
        row.update(path=str(target), probe=probe, below_480p=probe["height"] < 480,
            download_seconds=time.perf_counter()-started)
        try:
            row["crop"] = qc.crop(target, probe["width"], probe["height"])
        except Exception as exc:
            row.update(crop=None, crop_error=str(exc))
        row.update(status="ready", seconds=time.perf_counter()-started)
    except Exception as exc:
        error = str(exc)
        blocked = any(word in error.lower() for word in ["age-restricted", "age restricted", "sign in", "private video", "not available", "unavailable", "copyright", "403", "blocked", "removed", "members-only"])
        row.update(status="blocked" if blocked else "failed", error=error, seconds=time.perf_counter()-started)
    save_json(output, row)
    print(f"{video['id']}: {row['status']} {row.get('title', '')}", flush=True)
    return row


def run(project):
    folder = project/"media"/"jev"
    videos = prepare_project(project)
    cache = pool.cache_dir(project)/"jev-proxies"
    cache.mkdir(parents=True, exist_ok=True)
    report = dict(status="downloading", total=len(videos), videos=[])
    save_json(folder/"download-report.json", report)
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [executor.submit(download, video, cache, folder) for video in videos]
        for task in as_completed(tasks):
            report["videos"].append(task.result())
            save_json(folder/"download-report.json", report)
    report["status"] = "complete"
    save_json(folder/"download-report.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    run(parser.parse_args().project)
