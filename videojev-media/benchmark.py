# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stage 0b and matched warm timing checks; run with the model venv and a job JSON."""
import hashlib
import importlib
import json
import os
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

from demo import check_ready


def timed(torch, function):
    torch.cuda.synchronize()
    started = time.perf_counter()
    value = function()
    torch.cuda.synchronize()
    return value, time.perf_counter() - started


def estimate(case, seconds, load_seconds=0):
    windows = seconds / case["duration_seconds"]
    per_window = case["prepare_seconds"] + case["encode_median_seconds"] + case["batch40_seconds"]
    return load_seconds + windows * per_window


def run(job, result, save):
    cache = Path(job["cache_dir"])
    cache.mkdir(parents=True, exist_ok=True)
    for name, folder in [("HF_HOME", "hf"), ("HF_MODULES_CACHE", "modules"),
                         ("TRITON_CACHE_DIR", "triton"), ("TORCHINDUCTOR_CACHE_DIR", "inductor")]:
        os.environ[name] = str(cache / folder)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["FLA_INTRACARD_CP"] = "0"
    os.environ["HF_HUB_OFFLINE"] = "1"
    for name in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]:
        os.environ[name] = "2"
    import torch
    from importlib.metadata import version
    from transformers import AutoModel, AutoProcessor

    result["versions"] = {name: version(name) for name in
        ["torch", "torchvision", "transformers", "av", "flash-linear-attention", "fla-core"]}
    result["torch_cpu_threads"] = torch.get_num_threads()
    if job["attention"] == "flash_attention_2":
        result["versions"].update({name: version(name) for name in ["flash-attn", "causal-conv1d", "triton"]})
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    free, total = torch.cuda.mem_get_info()
    check_ready(job["comfy_queue"], free / 2**20, 12288)
    result.update(gpu=torch.cuda.get_device_name(), free_vram_mib=free / 2**20,
                  total_vram_mib=total / 2**20, attention=job["attention"], cases=[])
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    result["pins"] = config["model"]
    model_path = Path(job["model_path"])
    audited = list(Path(job["audit_dir"]).glob("*.py"))
    if len(audited) != 6 or {p.name for p in audited} != {p.name for p in model_path.glob("*.py")}:
        raise RuntimeError("Expected exactly the six audited remote-code modules")
    for path in audited:
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256((model_path / path.name).read_bytes()).digest():
            raise RuntimeError(f"Model source differs from audit: {path.name}")

    result["phase"] = "load"
    save()
    torch.cuda.reset_peak_memory_stats()
    def load():
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
        model = AutoModel.from_pretrained(model_path, trust_remote_code=True, local_files_only=True,
            dtype=torch.bfloat16, device_map={"": "cuda:0"}, attn_implementation=job["attention"])
        model.prepare_for_inference()
        return processor, model
    (processor, model), result["load_seconds"] = timed(torch, load)
    result["attention_readback"] = dict(model=model.config._attn_implementation,
        text=model.backbone.config.text_config._attn_implementation,
        vision=model.backbone.config.vision_config._attn_implementation)
    native = importlib.import_module(model.__class__.__module__)
    demo_questions = [
        {"id": "grounding-1", "task": "grounding", "query": "The woman in green eats pasta."},
        {"id": "qa-1", "task": "choice", "query": "What is the woman in green eating?",
         "options": ["A. Pasta.", "B. Rice.", "C. Soup."]},
    ]
    result["phase"] = "demo"
    save()
    def predict_demo():
        return model.predict_video(processor, job["demo_path"], demo_questions,
            fps=2.0, max_frames=2048, context=8192)
    result["demo_outputs"], result["demo_first_seconds"] = timed(torch, predict_demo)
    _, result["demo_warm_seconds"] = timed(torch, predict_demo)
    result["demo_peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
    result["demo_peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
    grounding, choice = result["demo_outputs"]
    if grounding["interval"] != [3.0, 10.0] or choice["answer_index"] != 0:
        raise RuntimeError("Stage 0b demo answers differ from the pinned README")
    result["demo_passed"] = True
    save()

    questions = job["questions"]
    assert len(questions) == 40 and len({q["id"] for q in questions}) == 40
    for case_job in job["cases"]:
        case = {key: case_job[key] for key in ["name", "duration_seconds", "fps", "sha256"]}
        result["cases"].append(case)
        result["phase"] = case["name"] + ":prepare"
        save()
        path = Path(case_job["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
            raise RuntimeError(f"Benchmark input hash mismatch: {path}")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        (pixels, record), case["prepare_seconds"] = timed(torch, lambda: native.prepare_video(
            processor, path, fps=case["fps"], max_frames=2048, context=32768))
        if abs(record["fps"] - case["fps"]) > 1e-8:
            raise RuntimeError("Frame cap silently changed benchmark fps")
        case["record"] = {key: record[key] for key in
                          ["frames", "fps", "grid_thw", "tokens", "sampled_duration"]}
        grid = torch.tensor([record["grid_thw"]])
        result["phase"] = case["name"] + ":encode-warmup"
        save()
        def encode():
            return model.encode_video(pixels, grid, groups_per_chunk=16)
        features, case["encode_first_seconds"] = timed(torch, encode)
        del features
        case["encode_seconds"] = []
        for repeat in range(2):
            features, seconds = timed(torch, encode)
            case["encode_seconds"].append(seconds)
            if repeat == 0:
                del features
        case["encode_median_seconds"] = statistics.median(case["encode_seconds"])
        del pixels
        result["phase"] = case["name"] + ":single-questions"
        save()
        def predict(rows):
            return model.predict_features(processor, features, record, rows, context=32768)
        predict(questions[:1])
        torch.cuda.synchronize()
        case["single_questions"] = []
        for question in questions[:3]:
            times = []
            for _ in range(2):
                _, seconds = timed(torch, lambda: predict([question]))
                times.append(seconds)
            case["single_questions"].append(dict(id=question["id"], seconds=times))
        case["single_question_median_seconds"] = statistics.median(
            value for row in case["single_questions"] for value in row["seconds"])
        groups = list(native.prepare_query_groups(processor, record, questions, 32768))
        case["query_group_lengths"] = [batch["input_ids"].shape[1] for batch, _ in groups]
        del groups
        result["phase"] = case["name"] + ":batch40-warmup"
        save()
        _, case["batch40_first_seconds"] = timed(torch, lambda: predict(questions))
        result["phase"] = case["name"] + ":batch40-timed"
        save()
        outputs, case["batch40_seconds"] = timed(torch, lambda: predict(questions))
        assert len(outputs) == 40
        case["batch40_per_question_seconds"] = case["batch40_seconds"] / 40
        case["peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
        case["peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
        case["context"] = 32768
        case["groups_per_chunk"] = 16
        del features, outputs
        save()
    result["estimates_seconds"] = {
        ("three_hour_coarse_40q" if case["name"] == "long" else "three_hour_fine_40q_full_coverage"):
        estimate(case, 10800, result["load_seconds"]) for case in result["cases"]
    }
    result["status"] = "passed"
    result["phase"] = "complete"


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    output = Path(job["result_path"])
    result = {"status": "running", "phase": "imports"}
    def save():
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(result["phase"], flush=True)
    stopped = threading.Event()
    def heartbeat():
        while not stopped.is_set():
            output.with_suffix(".heartbeat.json").write_text(json.dumps(
                dict(time=time.time(), phase=result["phase"])), encoding="utf-8")
            stopped.wait(20)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        run(job, result, save)
    except Exception as exc:
        result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
    finally:
        result["wall_seconds"] = time.perf_counter() - started
        torch = sys.modules.get("torch")
        if result["status"] == "failed" and torch is not None and torch.cuda.is_initialized():
            result["failure_peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
            result["failure_peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
        save()
        stopped.set()
        thread.join()
    sys.exit(0 if result["status"] == "passed" else 1)
