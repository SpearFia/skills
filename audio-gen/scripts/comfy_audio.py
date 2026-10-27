# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate music beds and sound effects with Stable Audio 3 through ComfyUI's API.

Usage:
  python comfy_audio.py --prompt TEXT --seconds 8 --out FILE.wav [--seed N] [--steps 8]
  python comfy_audio.py --jobs jobs.json        [{"prompt", "seconds", "out", "seed"?}, ...]
  python comfy_audio.py --self-test             checks the graph offline
  python comfy_audio.py --self-test --live      also generates a 3 s clip

ComfyUI must be running (default http://127.0.0.1:8188, or COMFYUI_URL) with
stable_audio_3_medium.safetensors and t5gemma_b_b_ul2.safetensors installed. Outputs are
converted to WAV with ffmpeg. Existing outputs are kept unless --force. Standard library
only.
"""

import hashlib
import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CHECKPOINT = "stable_audio_3_medium.safetensors"
TEXT_ENCODER = "t5gemma_b_b_ul2.safetensors"


def url():
    return os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def graph(prompt, seconds, seed, steps, prefix):
    """The Stable Audio 3 Medium workflow, flattened to API format (no prompt rewriting:
    the agent writes the final prompt)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": TEXT_ENCODER, "type": "stable_audio", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "5": {"class_type": "EmptyLatentAudio", "inputs": {"seconds": seconds, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "lcm", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudio", "inputs": {"audio": ["7", 0], "filename_prefix": prefix}},
    }


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url()}{path}", data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return raw if path.startswith("/view") else json.loads(raw)


def generate(job, steps, timeout=1800):
    out = Path(job["out"])
    seed = int(job.get("seed", random.randrange(2**31)))
    prefix = f"spearfia/{out.stem}"
    sent = call("/prompt", {"prompt": graph(job["prompt"], float(job["seconds"]), seed, steps,
                                            prefix), "client_id": str(uuid.uuid4())})
    if sent.get("node_errors"):
        raise RuntimeError(f"ComfyUI rejected the graph: {sent['node_errors']}")
    pid = sent["prompt_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        hist = call(f"/history/{pid}").get(pid)
        if hist:
            status = hist.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI failed: {status.get('messages')}")
            files = [f for o in hist.get("outputs", {}).values() for f in o.get("audio", [])]
            if files:
                f = files[0]
                raw = call("/view?" + urllib.parse.urlencode(
                    {"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                     "type": f.get("type", "output")}))
                return save_wav(raw, Path(f["filename"]).suffix, out), seed
        time.sleep(1.0)
    raise RuntimeError(f"ComfyUI didn't finish {out.name} within {timeout} s")


def save_wav(raw, suffix, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix or '.flac'}"
        src.write_bytes(raw)
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "pcm_s16le",
                            str(out)], capture_output=True, text=True, check=False)
        if r.returncode:
            raise RuntimeError(f"ffmpeg couldn't convert the output: {r.stderr.strip()}")
    return out


def seconds_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "csv=p=0", str(path)], capture_output=True, text=True, check=False)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return None


def run_jobs(jobs, steps, force):
    try:
        call("/system_stats")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"ComfyUI isn't answering at {url()} ({e}). Start it first.")
    results = []
    for job in jobs:
        out = Path(job["out"])
        proof=out.with_suffix(out.suffix+".request.json")
        key=hashlib.sha256(json.dumps({"job":job,"steps":steps,"url":url()},sort_keys=True).encode()).hexdigest()
        previous=json.loads(proof.read_text(encoding="utf-8")) if proof.exists() else {}
        if previous.get("state")=="uncertain" and not force:
            results.append({"out":str(out),"error":"Inspect ComfyUI before --force; the previous request may still exist. Prefer native jobs_run for resumable prompt IDs."});continue
        if out.exists() and not force:
            if previous.get("request_hash")!=key or previous.get("output_hash")!=hashlib.sha256(out.read_bytes()).hexdigest():
                results.append({"out":str(out),"error":"Existing output has no matching request/content proof."});continue
            results.append({"out": str(out), "kept": True, "seconds": seconds_of(out)})
            continue
        out.parent.mkdir(parents=True,exist_ok=True)
        proof.write_text(json.dumps({"request_hash":key,"state":"uncertain"}),encoding="utf-8")
        try:
            path, seed = generate(job, steps)
            proof.write_text(json.dumps({"request_hash":key,"output_hash":hashlib.sha256(path.read_bytes()).hexdigest(),"state":"complete","seed":seed}),encoding="utf-8")
            results.append({"out": str(path), "seed": seed, "prompt": job["prompt"],
                            "seconds": seconds_of(path)})
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            results.append({"out": str(out), "error": str(e)})
    print(json.dumps(results, indent=2))
    return 1 if any("error" in r for r in results) else 0


def self_test(live):
    g = graph("big cinematic hit", 3, 7, 8, "spearfia/test")
    assert g["6"]["inputs"]["seed"] == 7 and g["5"]["inputs"]["seconds"] == 3
    for node in g.values():  # every link points at a node that exists
        for v in node["inputs"].values():
            if isinstance(v, list):
                assert v[0] in g, v
    if live:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hit.wav"
            assert run_jobs([{"prompt": "single deep cinematic impact hit, short tail",
                              "seconds": 3, "out": str(out), "seed": 1}], 8, False) == 0
            secs = seconds_of(out)
            assert secs and 2.5 <= secs <= 3.5, secs
    print("self-test passed" + (" (live)" if live else ""))


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--self-test":
        self_test("--live" in argv)
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--prompt")
    p.add_argument("--seconds", type=float)
    p.add_argument("--out")
    p.add_argument("--seed", type=int)
    p.add_argument("--jobs", help="JSON file with a list of {prompt, seconds, out, seed?}")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    if a.jobs:
        jobs = json.loads(Path(a.jobs).read_text("utf-8"))
    elif a.prompt and a.seconds and a.out:
        jobs = [{"prompt": a.prompt, "seconds": a.seconds, "out": a.out,
                 **({"seed": a.seed} if a.seed is not None else {})}]
    else:
        p.error("give --prompt, --seconds and --out, or --jobs")
    sys.exit(run_jobs(jobs, a.steps, a.force))


if __name__ == "__main__":
    main()
