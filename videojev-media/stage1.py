# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stage 1 grounding accuracy at three bounded contexts; no persisted features."""
import hashlib
import importlib
import json
import math
import os
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

from benchmark import timed
from demo import check_ready


def summarize(probabilities, bounds, offset, threshold=0.5):
    if not probabilities or len(probabilities) != len(bounds):
        raise ValueError("Scores must match nonempty score bounds")
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("Expected finite probabilities in [0, 1]")
    runs, selected = [], []
    for i, p in enumerate(probabilities):
        if p >= threshold:
            if runs and i - runs[-1][-1] <= 2:
                runs[-1].append(i)
            else:
                runs.append([i])
    spans = []
    for run in runs:
        first, last = run[0], run[-1]
        if bounds[last][1] - bounds[first][0] >= 1.5:
            spans.append(dict(start=offset+bounds[first][0], end=offset+bounds[last][1],
                mean=statistics.mean(probabilities[first:last+1])))
    for index in sorted(range(len(probabilities)), key=lambda i: probabilities[i], reverse=True):
        if all(abs(index - prior) > 1 for prior in selected):
            selected.append(index)
        if len(selected) == 3:
            break
    return dict(max=max(probabilities), mean=statistics.mean(probabilities),
        p95=sorted(probabilities)[math.ceil(0.95*len(probabilities))-1],
        seconds_ge_050=sum(b-a for p, (a,b) in zip(probabilities,bounds) if p >= threshold),
        cells_ge_050=sum(p >= threshold for p in probabilities), spans=spans, top_cells=selected)


def evaluate(torch, native, model, processor, source, context, questions, save):
    result = dict(source=source["id"], context=context, source_start=source["source_start"],
                  duration=source["duration"], fps=source["fps"], status="running", queries=[])
    try:
        path = Path(source["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Input hash mismatch")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        image_budget = context
        prompts = importlib.import_module(native.prepare_query_groups.__module__)
        result["budget_attempts"] = []
        while True:
            pixels, record = native.prepare_video(processor, path, fps=source["fps"],
                max_frames=2048, context=image_budget)
            lengths = [prompts.native_inputs(processor, record, [q])[0].shape[1] for q in questions]
            required = (max(lengths)+63)//64*64
            result["budget_attempts"].append(dict(preprocess_context=image_budget,
                video_tokens=record["tokens"], longest_padded_prompt=required))
            if required <= context:
                break
            allowed = record["tokens"] - (required-context) - 64
            image_budget = min(image_budget-64, allowed*5//4)
            if image_budget < 64:
                raise ValueError("Complete grounding question cannot fit with the minimum video budget")
            del pixels
        result["prepare_seconds"] = time.perf_counter()-started
        result["preprocess_context"] = image_budget
        if abs(record["fps"]-source["fps"]) > 1e-8:
            raise ValueError("Frame cap silently changed fps")
        result["record"] = record
        grid = torch.tensor([record["grid_thw"]])
        features, result["encode_seconds"] = timed(torch, lambda: model.encode_video(pixels, grid, groups_per_chunk=16))
        del pixels
        result["feature_bytes"] = features.numel() * features.element_size()
        result["encode_peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
        result["encode_peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
        _, result["warmup_seconds"] = timed(torch, lambda: model.predict_features(
            processor, features, record, questions[:1], context=context))
        for question in questions:
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            outputs, seconds = timed(torch, lambda: model.predict_features(
                processor, features, record, [question], context=context))
            row = dict(question=question, seconds=seconds, probabilities=outputs[0]["probabilities"],
                peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
                peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20)
            row["summary"] = summarize(row["probabilities"], record["score_bounds"], source["source_start"])
            result["queries"].append(row)
            save(result)
        result["status"] = "complete"
    except Exception as exc:
        result.update(status="failed", error=str(exc), traceback=traceback.format_exc(),
            failure_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
            failure_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20)
    return result


def run(job, result, save):
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    if any(c not in [8192, 16384, 32768] or c > config["context_limit"] for c in job["contexts"]):
        raise ValueError("Stage 1 contexts must be 8192, 16384 or 32768, never higher")
    for key, folder in [("HF_HOME","hf"),("HF_MODULES_CACHE","modules"),("TRITON_CACHE_DIR","triton")]:
        os.environ[key] = str(Path(job["cache_dir"])/folder)
    for key in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]:
        os.environ[key] = "2"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["FLA_INTRACARD_CP"] = "0"
    import torch
    from transformers import AutoModel, AutoProcessor
    check_ready(job["comfy_queue"], torch.cuda.mem_get_info()[0]/2**20, 12288)
    model_path = Path(job["model_path"])
    audited = list(Path(job["audit_dir"]).glob("*.py"))
    if len(audited) != 6:
        raise ValueError("Missing reviewed model source")
    for path in audited:
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256((model_path/path.name).read_bytes()).digest():
            raise ValueError("Model source differs from pinned audit")
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(model_path, trust_remote_code=True, local_files_only=True,
        dtype=torch.bfloat16, device_map={"":"cuda:0"}, attn_implementation="flash_attention_2")
    model.prepare_for_inference()
    native = importlib.import_module(model.__class__.__module__)
    result.update(pins=config["model"], feature_files_written=0, cases=[], alignment=[])
    for test in job["alignment"]:
        _, record = native.prepare_video(processor, test["path"], fps=test["fps"], max_frames=2048, context=8192)
        actual = [test["source_start"]+f["selected_time"] for f in test["frames"]]
        errors = [test["source_start"]+t-(actual[2*i]+actual[min(2*i+1,len(actual)-1)])/2
                  for i,t in enumerate(record["score_times"])]
        result["alignment"].append(dict(fps=test["fps"], rounding=test["rounding"], record=record,
            pair_time_errors=errors, max_abs_pair_error=max(map(abs,errors))))
    for source in job["sources"]:
        for context in job["contexts"]:
            result["phase"] = f"{source['id']} / {context}"
            save()
            def save_case(case):
                result["active_case"] = case
                save()
            case = evaluate(torch, native, model, processor, source, context, job["questions"], save_case)
            result["cases"].append(case)
            result.pop("active_case", None)
            save()
    result["status"] = "complete" if all(c["status"] == "complete" for c in result["cases"]) else "completed_with_failures"
    result["phase"] = "complete"


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    output = Path(job["result_path"])
    result = dict(status="running", phase="load")
    def save():
        output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        print(result["phase"], flush=True)
    stopped = threading.Event()
    def heartbeat():
        while not stopped.is_set():
            output.with_suffix(".heartbeat.json").write_text(json.dumps(dict(time=time.time(),phase=result["phase"])))
            stopped.wait(20)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        run(job,result,save)
    except Exception as exc:
        result.update(status="failed",error=str(exc),traceback=traceback.format_exc())
    finally:
        save()
        stopped.set()
        thread.join()
    sys.exit(0 if result["status"] == "complete" else 1)
