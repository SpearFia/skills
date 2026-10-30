# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run the pinned README demo in the isolated model environment: demo.py job.json."""
import hashlib
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path


def check_ready(queue, free_mib, minimum_mib):
    if not isinstance(queue, dict) or any(not isinstance(queue.get(key), list)
                                         for key in ("queue_running", "queue_pending")):
        raise RuntimeError("Unexpected ComfyUI queue response; cannot verify it is idle.")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI has queued or running jobs; wait until it is idle.")
    if free_mib < minimum_mib:
        raise RuntimeError(f"Only {free_mib:.0f} MiB VRAM free; need {minimum_mib} MiB.")


def run(job, result):
    cache = Path(job["cache_dir"])
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    os.environ["HF_HOME"] = str(cache / "hf")
    os.environ["HF_MODULES_CACHE"] = str(cache / "hf-modules")
    os.environ["TRITON_CACHE_DIR"] = str(cache / "triton")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["FLA_INTRACARD_CP"] = "0"

    import torch
    from huggingface_hub import hf_hub_download, snapshot_download
    from transformers import AutoModel, AutoProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in this environment.")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5) as response:
            queue = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError("Cannot verify ComfyUI is idle at localhost:8188.") from exc
    free, total = torch.cuda.mem_get_info()
    result.update(gpu=torch.cuda.get_device_name(), total_vram_mib=total / 2**20,
                  free_vram_mib=free / 2**20, pins=config)
    check_ready(queue, free / 2**20, config["runtime"]["min_free_vram_mib"])
    result["comfy_queue"] = {"running": len(queue["queue_running"]),
                             "pending": len(queue["queue_pending"])}

    started = time.perf_counter()
    demo = config["demo"]
    video = hf_hub_download(repo_id=demo["repository"], filename=demo["filename"],
                            repo_type="dataset", revision=demo["revision"])
    model_config = config["model"]
    snapshot = Path(snapshot_download(repo_id=model_config["id"],
        revision=model_config["revision"], allow_patterns=["*.json", "*.py", "*.safetensors", "*.jinja"]))
    audited_files = list((cache / "hf-audit" / model_config["code_revision"]).glob("*.py"))
    assert len(audited_files) == 6, "Expected six previously reviewed remote-code modules"
    assert {p.name for p in snapshot.glob("*.py")} == {p.name for p in audited_files}
    for audited in audited_files:
        if hashlib.sha256(audited.read_bytes()).digest() != hashlib.sha256((snapshot / audited.name).read_bytes()).digest():
            raise RuntimeError(f"Downloaded remote code differs from audit: {audited.name}")
    result["download_seconds"] = time.perf_counter() - started
    print(f"Downloads ready in {result['download_seconds']:.2f}s", flush=True)

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_config["id"],
        revision=model_config["revision"], code_revision=model_config["code_revision"], trust_remote_code=True)
    model = AutoModel.from_pretrained(model_config["id"],
        revision=model_config["revision"], code_revision=model_config["code_revision"],
        trust_remote_code=True, dtype=torch.bfloat16, device_map={"": "cuda:0"},
        attn_implementation=config["runtime"]["attn_implementation"])
    model.prepare_for_inference()
    torch.cuda.synchronize()
    result["load_seconds"] = time.perf_counter() - started
    result["attention"] = {"model": model.config._attn_implementation,
        "text": model.backbone.config.text_config._attn_implementation,
        "vision": model.backbone.config.vision_config._attn_implementation}
    print(f"Model loaded in {result['load_seconds']:.2f}s; attention={result['attention']}", flush=True)

    questions = [
        {"id": "grounding-1", "task": "grounding", "query": "The woman in green eats pasta."},
        {"id": "qa-1", "task": "choice", "query": "What is the woman in green eating?",
         "options": ["A. Pasta.", "B. Rice.", "C. Soup."]},
    ]
    started = time.perf_counter()
    result["outputs"] = model.predict_video(processor, video, questions,
        fps=demo["fps"], max_frames=demo["max_frames"], context=demo["context"])
    torch.cuda.synchronize()
    result["inference_seconds"] = time.perf_counter() - started
    grounding, choice = result["outputs"]
    a, b = grounding["interval"]
    result["comparison"] = {
        "readme_interval": [3.0, 10.0], "readme_answer": "A. Pasta.",
        "interval_iou": max(0, min(b, 10) - max(a, 3)) / (max(b, 10) - min(a, 3)),
        "choice_matches": choice["answer_index"] == 0,
    }
    result["status"] = "passed" if choice["answer_index"] == 0 and result["comparison"]["interval_iou"] >= 0.5 else "failed"


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    result = {"status": "failed"}
    started = time.perf_counter()
    try:
        run(job, result)
    except Exception as exc:
        result.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        result["wall_seconds"] = time.perf_counter() - started
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            result["peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
            result["peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
        Path(job["result_path"]).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)
    sys.exit(0 if result["status"] == "passed" else 1)
