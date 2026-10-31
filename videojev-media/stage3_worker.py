# SPDX-License-Identifier: MIT OR Apache-2.0
"""Resident Ubuntu model worker. Each request/result is an atomic JSON file."""
import hashlib
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

from benchmark import timed
from demo import check_ready


def save(path, value):
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value)+"\n", encoding="utf-8")
    temporary.replace(path)


def infer(torch, native, model, processor, task):
    context = 32768
    if task["context"] != context:
        raise ValueError("Every Stage 3 request must use context 32,768")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    budget, attempts = context, []
    prompts = importlib.import_module(native.prepare_query_groups.__module__)
    while True:
        pixels, record = native.prepare_video(processor, task["path"], fps=task["fps"], max_frames=2048, context=budget)
        longest = max((prompts.native_inputs(processor, record, [q])[0].shape[1]+63)//64*64 for q in task["questions"])
        attempts.append(dict(preprocess_context=budget, video_tokens=record["tokens"], longest_prompt=longest))
        if longest <= context:
            break
        allowed = record["tokens"]-(longest-context)-64
        budget = min(budget-64, allowed*5//4)
        del pixels
        if budget < 64:
            raise ValueError("Complete question does not fit the fixed context")
    if abs(record["fps"]-task["fps"]) > 1e-8:
        raise ValueError("The frame cap silently changed the requested fps")
    prepare_seconds = time.perf_counter()-started
    features, encode_seconds = timed(torch, lambda: model.encode_video(pixels, torch.tensor([record["grid_thw"]]), groups_per_chunk=16))
    del pixels
    rows = []
    encode_peak = torch.cuda.max_memory_allocated()/2**20
    for question in task["questions"]:
        torch.cuda.reset_peak_memory_stats()
        outputs, seconds = timed(torch, lambda: model.predict_features(processor, features, record, [question], context=context))
        rows.append(dict(question=question, output=outputs[0], seconds=seconds,
            peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
            peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20))
    feature_bytes = features.numel()*features.element_size()
    del features
    return dict(status="complete", record=record, queries=rows, context=context,
        prepare_seconds=prepare_seconds, encode_seconds=encode_seconds, encode_peak_allocated_mib=encode_peak,
        budget_attempts=attempts, feature_bytes_in_ram=feature_bytes, feature_files_written=0)


def run(job):
    for key, folder in [("HF_HOME", "hf"), ("HF_MODULES_CACHE", "modules"), ("TRITON_CACHE_DIR", "triton")]:
        os.environ[key] = str(Path(job["cache_dir"])/folder)
    for key in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]:
        os.environ[key] = "2"
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false", FLA_INTRACARD_CP="0")
    import torch
    from transformers import AutoModel, AutoProcessor
    check_ready(job["comfy_queue"], torch.cuda.mem_get_info()[0]/2**20, 12288)
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    model_path, audit = Path(job["model_path"]), Path(job["audit_dir"])
    files = list(audit.glob("*.py"))
    if len(files) != 6 or {p.name for p in files} != {p.name for p in model_path.glob("*.py")}:
        raise ValueError("Expected exactly the six reviewed model modules")
    for path in files:
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256((model_path/path.name).read_bytes()).digest():
            raise ValueError("Model code differs from the pinned audit")
    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(model_path, trust_remote_code=True, local_files_only=True,
        dtype=torch.bfloat16, device_map={"": "cuda:0"}, attn_implementation="flash_attention_2")
    model.prepare_for_inference()
    torch.cuda.synchronize()
    native = importlib.import_module(model.__class__.__module__)
    directory = Path(job["task_dir"])
    save(directory/"ready.json", dict(status="ready", load_seconds=time.perf_counter()-started,
        pins=config["model"], attention=model.config._attn_implementation,
        gpu=torch.cuda.get_device_name(), total_vram_mib=torch.cuda.mem_get_info()[1]/2**20))
    while not (directory/"stop").exists():
        requests = sorted(directory.glob("*.request.json"))
        for request in requests:
            result_path = request.with_name(request.name.replace(".request.json", ".result.json"))
            if result_path.exists():
                continue
            task = json.loads(request.read_text())
            save(directory/"active.json", dict(task=task["id"], started=time.time()))
            started = time.perf_counter()
            try:
                with torch.inference_mode():
                    result = infer(torch, native, model, processor, task)
            except Exception as exc:
                result = dict(status="failed", error=str(exc), traceback=traceback.format_exc())
                torch.cuda.empty_cache()
            result.update(id=task["id"], wall_seconds=time.perf_counter()-started)
            save(result_path, result)
            print(task["id"], result["status"], f"{result['wall_seconds']:.2f}s", flush=True)
            if result.get("error") and "out of memory" in result["error"].lower():
                raise RuntimeError("4B exceeded available VRAM at the accepted settings; stopping")
        time.sleep(0.25)


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    try:
        run(job)
    except Exception as exc:
        save(Path(job["task_dir"])/"fatal.json", dict(error=str(exc), traceback=traceback.format_exc()))
        raise
