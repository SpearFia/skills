# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generate seamless loop clips (video with its own audio) with MiniMax H3 through ComfyUI.

Usage:
  python comfy_video.py --prompt TEXT --image REF.png --seconds 8 --out CLIP.mp4 [--seed N]
  python comfy_video.py --jobs jobs.json   [{"prompt", "image", "seconds", "out", "seed"?,
                                             "ref_prompt"?, "loop"?, "turbo"?, "steps"?}, ...]
  python comfy_video.py --self-test         checks the graphs offline

The reference image is anchored at the first and the last frame (MiniMaxH3AddGuide at
frame 0 and -1), so the clip ends where it starts and loops. "loop": false anchors the first
frame only. Every reference image and clip goes through qc.py; a fail is kept as
<name>.rejected-<n> and re-rolled with a new seed (--retries, default 2; --no-qc to skip).
"turbo": false renders with the base model (default 25 steps) instead of the 4-step
LoRA, for finals with stronger motion. If the image doesn't exist and "ref_prompt" is given, it is generated first with
MOSS-Image (16:9, no prompt rewriting). ComfyUI must be running (default
http://127.0.0.1:8188, or COMFYUI_URL). Existing outputs are kept unless --force. Standard
library only.
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import qc

H3 = {"ref2va_model": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
      "text_encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
      "video_vae": "minimax_h3_video_vae_int8_convrot.safetensors",
      "audio_vae": "minimax_h3_audio_vae_fp32.safetensors"}
TURBO_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
FPS = 24


def url():
    return os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def frames(seconds):
    """H3 works on a 17k + 5 frame grid; snap up to it."""
    n = max(5, round(seconds * FPS))
    return n + (-(n - 5)) % 17


def graph(prompt, image, seconds, seed, prefix, loop=True, resolution="720P", steps=4, turbo=True):
    """MiniMax_H3_Easy_English_Fixed.json in API format, in image mode, plus a last-frame
    guide for loops. `image` is a ComfyUI input file name. turbo=False drops the 4-step LoRA
    (Friends_H02_base20.json: base model, 20+ steps)."""
    g = {
        "1": {"class_type": "MiniMaxH3EasyLoader", "inputs": {"fl2va_model": "None", **H3}},
        "15": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "MiniMaxH3Easy",
              "inputs": {"h3_bundle": ["1", 0], "media": ["15", 0], "mode": "image",
                         "prompt": prompt, "resolution": resolution, "aspect_ratio": "16:9",
                         "width": 1344, "height": 768, "seconds": frames(seconds) / FPS,
                         "advanced": False, "fps": FPS, "keyframe_role": "first",
                         "ref_image_size": "match", "reference_mention_mode": "index",
                         "prompt_optimizer_settings": False,
                         "prompt_optimizer_scene_guide": "none"}},
        "13": {"class_type": "MiniMaxH3EasyOutput", "inputs": {"h3_context": ["2", 1]}},
        "24": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["2", 0], "lora_name": TURBO_LORA, "strength_model": 1.0}},
        "34": {"class_type": "ModelAttentionBackend",
               "inputs": {"model": ["24", 0], "attention": "pytorch attention"}},
        "4": {"class_type": "BasicGuider", "inputs": {"model": ["34", 0], "conditioning": ["13", 0]}},
        "5": {"class_type": "BasicScheduler",
              "inputs": {"model": ["34", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "SamplerCustomAdvanced",
              "inputs": {"noise": ["6", 0], "guider": ["4", 0], "sampler": ["7", 0],
                         "sigmas": ["5", 0], "latent_image": ["13", 1]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["13", 2]}},
        "10": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 1], "vae": ["13", 3]}},
        "11": {"class_type": "CreateVideo",
               "inputs": {"images": ["9", 0], "audio": ["10", 0], "fps": ["13", 4]}},
        "12": {"class_type": "SaveVideo",
               "inputs": {"video": ["11", 0], "filename_prefix": prefix, "format": "auto",
                          "codec": "auto"}},
    }
    if not turbo:
        del g["24"]
        g["34"]["inputs"]["model"] = ["2", 0]
    if loop:
        g["40"] = {"class_type": "MiniMaxH3AddGuide",
                   "inputs": {"positive": ["13", 0], "latent": ["13", 1], "frame_idx": -1,
                              "vae": ["13", 2], "image": ["15", 0]}}
        g["4"]["inputs"]["conditioning"] = ["40", 0]
    return g


def ref_graph(prompt, seed, prefix):
    """image_moss_image_t2i.json's subgraph, flattened, without the prompt rewriter."""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "kromoss_bf16.safetensors", "weight_dtype": "default"}},
        "25": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": "8-steps-dmd2-lora.safetensors",
                          "strength_model": 1.0}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3.5_9b_int8_convrot.safetensors",
                                                     "type": "moss_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae_small.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": "text, watermark, logo, faces, worst quality"}},
        # 1792x1024 has H3's 1.75:1 aspect; scaled exactly to 1344x768 so both loop anchors agree.
        "6": {"class_type": "EmptyFlux2LatentImage",
              "inputs": {"width": 1792, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["25", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": 8, "cfg": 1.0,
                         "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "10": {"class_type": "ImageScale",
               "inputs": {"image": ["8", 0], "upscale_method": "lanczos", "width": 1344,
                          "height": 768, "crop": "disabled"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def call(path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url()}{path}", data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = r.read()
    return out if raw else json.loads(out)


def upload(path):
    """Put a local image into ComfyUI's input folder; returns the name LoadImage takes."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    body += path.read_bytes() + (f"\r\n--{boundary}\r\nContent-Disposition: form-data; "
                                 f"name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(f"{url()}/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        info = json.loads(r.read())
    return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]


def run(g, out, kinds, timeout):
    """Queue a graph, wait, and save its first output file of one of `kinds` to `out`."""
    sent = call("/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})
    if sent.get("node_errors"):
        raise RuntimeError(f"ComfyUI rejected the graph: {sent['node_errors']}")
    pid = sent["prompt_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        hist = call(f"/history/{pid}").get(pid)
        if hist:
            if hist.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"ComfyUI failed: {hist['status'].get('messages')}")
            files = [f for o in hist.get("outputs", {}).values() for k in kinds for f in o.get(k, [])]
            if files:
                f = files[0]
                data = call("/view?" + urllib.parse.urlencode(
                    {"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                     "type": f.get("type", "output")}), raw=True)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
                return out
        time.sleep(2.0)
    raise RuntimeError(f"ComfyUI didn't finish {out.name} within {timeout} s")


def reroll(make, check, out, seed, retries):
    """make(seed) writes `out`; check(out) returns a qc report. A failed file is kept beside
    `out` as <stem>.rejected-<n><suffix> for review and the next seed is tried. Returns
    (seed, attempts) of the first pass; raises RuntimeError when every attempt fails."""
    attempts = []
    for n in range(retries + 1):
        s = seed + n * 1009
        make(s)
        report = check(out) if check else {"ok": True, "fails": []}
        attempts.append({"seed": s, "fails": report["fails"], "metrics": report.get("metrics")})
        if report["ok"]:
            return s, attempts
        out.replace(out.with_name(f"{out.stem}.rejected-{n + 1}{out.suffix}"))
    raise RuntimeError(f"{out.name} failed QC {retries + 1} times: {attempts[-1]['fails']}")


def generate(job, retries, qc_on, timeout=3600):
    out, image = Path(job["out"]), Path(job["image"])
    seed = int(job.get("seed", random.randrange(2**31)))
    started, record = time.time(), {}
    if not image.exists():
        if not job.get("ref_prompt"):
            raise RuntimeError(f"{image} doesn't exist and the job has no ref_prompt")
        rs, record["ref_attempts"] = reroll(
            lambda s: run(ref_graph(job["ref_prompt"], s, f"spearfia/{image.stem}"), image, ["images"], timeout),
            qc.check_image if qc_on else None, image, seed, retries)
        record["ref_seed"] = rs
    elif qc_on and not (r := qc.check_image(image))["ok"]:
        # Somebody else's reference image: report it rather than overwrite it.
        raise RuntimeError(f"reference image {image} fails QC: {r['fails']}")
    name = upload(image)
    turbo = job.get("turbo", True)
    steps = int(job.get("steps", 4 if turbo else 25))
    clip_seed, record["attempts"] = reroll(
        lambda s: run(graph(job["prompt"], name, float(job["seconds"]), s, f"spearfia/{out.stem}",
                            job.get("loop", True), job.get("resolution", "720P"), steps, turbo),
                      out, ["images", "videos", "gifs"], timeout),  # SaveVideo reports under "images"
        (lambda p: qc.check_clip(p, voice=job.get("voice_check", True))) if qc_on else None,
        out, seed, retries)
    return out, clip_seed, round(time.time() - started, 1), record


def run_jobs(jobs, force, retries=2, qc_on=True):
    try:
        call("/system_stats")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"ComfyUI isn't answering at {url()} ({e}). Start it first.")
    results = []
    for job in jobs:
        out = Path(job["out"])
        if out.exists() and not force:
            results.append({"out": str(out), "kept": True})
            continue
        try:
            path, seed, secs, record = generate(job, int(job.get("retries", retries)),
                                                qc_on and job.get("qc", True))
            results.append({"out": str(path), "seed": seed, "prompt": job["prompt"],
                            "image": job["image"], "loop": job.get("loop", True),
                            "turbo": job.get("turbo", True), "steps": job.get("steps"),
                            "generation_seconds": secs, **record})
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            results.append({"out": str(out), "error": str(e)})
    print(json.dumps(results, indent=2))
    return 1 if any("error" in r for r in results) else 0


def self_test():
    assert [frames(s) for s in (5, 8, 10)] == [124, 192, 243], [frames(s) for s in (5, 8, 10)]
    for g in (graph("p", "ref.png", 8, 7, "t"), graph("p", "ref.png", 8, 7, "t", loop=False),
              ref_graph("p", 7, "t")):
        for node in g.values():  # every link points at a node that exists
            for v in node["inputs"].values():
                if isinstance(v, list):
                    assert v[0] in g, v
    g = graph("p", "ref.png", 8, 7, "t")
    assert g["40"]["inputs"]["frame_idx"] == -1 and g["4"]["inputs"]["conditioning"] == ["40", 0]
    assert "40" not in graph("p", "ref.png", 8, 7, "t", loop=False)
    base = graph("p", "ref.png", 8, 7, "t", steps=25, turbo=False)
    assert "24" not in base and base["34"]["inputs"]["model"] == ["2", 0]
    assert base["5"]["inputs"]["steps"] == 25
    with tempfile.TemporaryDirectory() as tmp:  # re-rolls: fail, fail, pass
        out, verdicts = Path(tmp) / "c.mp4", iter([False, False, True])
        seed, tries = reroll(lambda s: out.write_text(str(s)),
                             lambda p: {"ok": next(verdicts), "fails": ["x"]}, out, 5, 2)
        assert seed == 5 + 2 * 1009 and len(tries) == 3 and out.read_text() == str(seed)
        assert sorted(p.name for p in Path(tmp).iterdir()) == ["c.mp4", "c.rejected-1.mp4", "c.rejected-2.mp4"]
        try:
            reroll(lambda s: out.write_text("x"), lambda p: {"ok": False, "fails": ["y"]}, out, 1, 0)
            raise AssertionError("expected a QC failure")
        except RuntimeError:
            pass
    print("self-test passed")


def main():
    if sys.argv[1:2] == ["--self-test"]:
        self_test()
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--prompt")
    p.add_argument("--image")
    p.add_argument("--ref-prompt")
    p.add_argument("--seconds", type=float, default=8)
    p.add_argument("--out")
    p.add_argument("--seed", type=int)
    p.add_argument("--no-loop", action="store_true")
    p.add_argument("--jobs", help="JSON file with a list of jobs (see above)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--retries", type=int, default=2, help="new seeds to try after a QC fail")
    p.add_argument("--no-qc", action="store_true", help="skip qc.py checks and re-rolls")
    a = p.parse_args()
    if a.jobs:
        jobs = json.loads(Path(a.jobs).read_text("utf-8"))
    elif a.prompt and a.image and a.out:
        jobs = [{"prompt": a.prompt, "image": a.image, "seconds": a.seconds, "out": a.out,
                 "loop": not a.no_loop,
                 **({"seed": a.seed} if a.seed is not None else {}),
                 **({"ref_prompt": a.ref_prompt} if a.ref_prompt else {})}]
    else:
        p.error("give --prompt, --image and --out, or --jobs")
    sys.exit(run_jobs(jobs, a.force, a.retries, not a.no_qc))


if __name__ == "__main__":
    main()
