# SPDX-License-Identifier: MIT OR Apache-2.0
"""Resumable three-round indexing, independent miss audit and choice confirmation."""
import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from stage3_sources import command, pool, qc, save_json
from jev import require_legacy


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def wsl_path(path):
    path = Path(path).resolve()
    return "/mnt/"+path.drive[0].lower()+"/"+path.as_posix().split(":/", 1)[1]


def union(intervals):
    result = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if result and a <= result[-1][1]+1e-6:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([a, b])
    return result


def subtract(a, b, excluded):
    result, cursor = [], a
    for lo, hi in union(excluded):
        if hi <= cursor or lo >= b:
            continue
        if lo > cursor:
            result.append([cursor, min(lo, b)])
        cursor = max(cursor, hi)
        if cursor >= b:
            break
    if cursor < b:
        result.append([cursor, b])
    return result


def merge_windows(windows, duration, maximum):
    merged = []
    for row in sorted(windows, key=lambda w: w["start"]):
        a, b = max(0., row["start"]), min(duration, row["end"])
        if b <= a:
            continue
        if merged and a <= merged[-1]["end"]+1e-6:
            merged[-1]["end"] = max(b, merged[-1]["end"])
            merged[-1]["needs"] = sorted(set(merged[-1]["needs"]) | set(row["needs"]))
        else:
            merged.append(dict(start=a, end=b, needs=sorted(set(row["needs"]))))
    chunks = []
    for row in merged:
        count = math.ceil((row["end"]-row["start"])/maximum)
        for i in range(count):
            a = row["start"]+i*maximum
            chunks.append(dict(start=a, end=min(row["end"], a+maximum), needs=row["needs"]))
    return chunks


def runs(probabilities, bounds, threshold, offset, black):
    selected = []
    for i, p in enumerate(probabilities):
        a, b = bounds[i]
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Invalid grounding probability")
        # Only score cells whose sampled input frames are both nonblack supply evidence.
        if p >= threshold and not black[i]:
            if selected and i-selected[-1][-1] <= 2 and not any(black[selected[-1][-1]+1:i]):
                selected[-1].append(i)
            else:
                selected.append([i])
    return [dict(start=offset+bounds[r[0]][0], end=offset+bounds[r[-1]][1],
        mean=sum(probabilities[r[0]:r[-1]+1])/(r[-1]-r[0]+1)) for r in selected]


def scope_status(video, need):
    title = video.get("title", "")
    chapter = re.search(r"John\s+Wick\s*(?::\s*)?(?:Chapter\s*)?([234])\b", title, re.I)
    if chapter and need["source_group"].startswith("wick"):
        return "conflict" if need["source_group"] != "wick"+chapter[1] else "title_matches_group"
    if need["source_group"].startswith("wick") and re.search(r"franchise|19 minutes|best scenes", title, re.I):
        return "mixed_films_review_required"
    if need["source_group"] == "gta6" and video.get("channel_id") != "UC6VcWc1rAoWdBCM0JxrRQ3A":
        return "official_source_review_required"
    if re.search(r"\bmods?\b|modded|gta online", title, re.I) and not need["source_group"].startswith("wick"):
        return "scope_review_required"
    return "creator_group_not_independently_verified"


class Indexer:
    def __init__(self, project):
        require_legacy(project)
        self.project = project
        self.folder = project/"media"/"jev"
        self.cache = pool.cache_dir(project)/"jev-index"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.tasks = self.cache/"tasks"
        self.tasks.mkdir(exist_ok=True)
        self.config = json.loads(Path(__file__).with_name("config.json").read_text())
        self.settings = self.config["index"]
        self.needs = {n["id"]: n for n in json.loads((self.folder/"needs.json").read_text(encoding="utf-8"))}
        self.inputs = json.loads((self.folder/"input-cues.json").read_text(encoding="utf-8"))
        self.state = dict(status="running", phase="startup", started=time.time(), windows=0, candidates=0)
        library = Path("D:/SpearFia/library/jev")
        library.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(library/"index.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS scores (video_id TEXT, query_hash TEXT, round INTEGER, t0 REAL, t1 REAL, p REAL, window_id TEXT, PRIMARY KEY(video_id,query_hash,round,t0,t1,window_id))")
        self.db.execute("CREATE INDEX IF NOT EXISTS scores_query ON scores(video_id,query_hash,round)")
        self.candidates, self.windows, self.representative, self.timings = [], [], [], []
        self.worker = None

    def status(self, phase):
        self.state.update(phase=phase, updated=time.time(), windows=len(self.windows), candidates=len(self.candidates))
        save_json(self.folder/"index-status.json", self.state)
        print(phase, flush=True)

    def start_worker(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=3) as response:
                queue = json.load(response)
        except urllib.error.URLError:
            # An absent server is idle only after checking the Windows process list.
            active = command(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|comfy' -and $_.CommandLine -match 'ComfyUI|main.py' } | Select-Object -ExpandProperty ProcessId"], 30).strip()
            if active:
                raise RuntimeError("ComfyUI process exists but its queue cannot be checked")
            queue = {"queue_running": [], "queue_pending": []}
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise RuntimeError("ComfyUI must be idle")
        for name in ["stop", "ready.json", "fatal.json"]:
            (self.tasks/name).unlink(missing_ok=True)
        job = dict(task_dir=wsl_path(self.tasks), cache_dir="/home/caesar/videojev/stage1/cache",
            model_path="/home/caesar/videojev/model", comfy_queue=queue,
            audit_dir="/mnt/c/Users/caesa/AppData/Local/SpearFia/cache/videojev/hf-audit/"+self.config["model"]["code_revision"])
        path = self.cache/"worker-job.json"
        save_json(path, job)
        log = (self.cache/"worker.log").open("a", encoding="utf-8")
        self.worker = subprocess.Popen(["wsl", "-d", "Ubuntu", "--", "/home/caesar/videojev/venv/bin/python", "-u",
            wsl_path(Path(__file__).with_name("stage3_worker.py")), wsl_path(path)], stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW)
        started = time.time()
        while not (self.tasks/"ready.json").exists():
            self.check_worker()
            if time.time()-started > 600:
                raise TimeoutError("Model worker did not become ready")
            time.sleep(1)
        self.state["worker"] = json.loads((self.tasks/"ready.json").read_text())

    def check_worker(self):
        if (self.tasks/"fatal.json").exists():
            raise RuntimeError((self.tasks/"fatal.json").read_text())
        if self.worker.poll() is not None:
            raise RuntimeError("Ubuntu worker exited; inspect worker.log")

    def predict(self, video, a, b, fps, questions, sample_from=None):
        # shortcut: changed question groups recompute that window; split cache keys if repeated re-querying becomes common.
        identity = dict(version=1, video=video["id"], size=Path(video["path"]).stat().st_size,
            start=round(a, 6), end=round(b, 6), fps=fps, crop=video.get("crop"), context=32768,
            pins=self.config["model"], questions=questions)
        if sample_from:
            identity['sample_origin']=dict(start=sample_from['start'],clip=Path(sample_from['path']).stem)
        key = digest(identity)
        result_path = self.tasks/(key+".result.json")
        clip_key = digest({k:v for k,v in identity.items() if k != "questions"})
        clip = self.cache/(clip_key+".mp4")
        if sample_from and abs(a-sample_from['start'])<1e-6 and abs(b-sample_from['end'])<1e-6:
            clip=Path(sample_from['path'])
        self.last_sample=dict(path=str(clip),start=a,end=b,video_id=video['id'],fps=fps)
        sampling_seconds,waiting_seconds = 0.,0.
        cache_hit=result_path.exists()
        if not result_path.exists():
            if not clip.exists():
                started = time.perf_counter()
                crop = None if sample_from else video.get("crop")
                source_path=sample_from['path'] if sample_from else video['path']
                seek=a-sample_from['start'] if sample_from else a
                filters = (f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else "")
                filters += f"fps={fps}:start_time=0:round=up,trim=duration={b-a:.6f}"
                command(["ffmpeg", "-v", "error", "-y", "-ss", f"{seek:.6f}", "-t", f"{b-a:.6f}",
                    "-i", source_path, "-an", "-vf", filters, "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "18", "-g", "1", "-threads", "2", "-t", f"{b-a:.6f}", str(clip)], 600)
                sampling_seconds = time.perf_counter()-started
                save_json(clip.with_suffix('.sample.json'),dict(seconds=sampling_seconds,input=source_path,
                    reused_round3=bool(sample_from),source_start=a,source_end=b))
            save_json(self.tasks/(key+".request.json"), dict(id=key, path=wsl_path(clip), fps=fps, questions=questions, context=32768))
            started = time.time()
            while not result_path.exists():
                self.check_worker()
                if time.time()-started > 1800:
                    raise TimeoutError("Model request exceeded 30 minutes")
                time.sleep(.05)
            waiting_seconds=time.time()-started
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result["status"] != "complete":
            raise RuntimeError(result.get("error", "Model request failed"))
        self.timings.append(dict(video_id=video["id"], task=key, start=a, end=b, fps=fps,
            sampling_seconds=sampling_seconds, prepare_seconds=result["prepare_seconds"], encode_seconds=result["encode_seconds"],
            cache_hit=cache_hit,wait_for_result_seconds=waiting_seconds,
            wait_overhead_seconds=max(0,waiting_seconds-result.get('wall_seconds',0)),
            worker_idle_before_seconds=result.get('idle_before_seconds',0),sample_from_round3=bool(sample_from),
            queries=[dict(id=q["question"]["id"], seconds=q["seconds"], peak_allocated_mib=q["peak_allocated_mib"],
                peak_reserved_mib=q["peak_reserved_mib"]) for q in result["queries"]]))
        return key, result

    def black_ranges(self, video):
        path = self.cache/(video["id"]+".black.json")
        if path.exists():
            return json.loads(path.read_text())["ranges"]
        crop = video.get("crop")
        filters = (f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else "")
        filters += f"blackdetect=d=0.01:pic_th={self.settings['black_picture_ratio']}:pix_th={self.settings['black_pixel_threshold']}"
        started = time.perf_counter()
        output = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-threads", "2", "-i", video["path"],
            "-vf", filters, "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=1800)
        if output.returncode:
            raise RuntimeError(output.stderr[-2000:])
        ranges = [[float(a), float(b)] for a,b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", output.stderr)]
        save_json(path, dict(ranges=ranges, seconds=time.perf_counter()-started, settings=filters))
        return ranges

    def score_window(self, video, window, round_number, black_ranges, audit=False):
        fps = self.settings["fps"][round_number-1]
        questions = [dict(id=key+f"-v{i}", task="grounding", query=query) for key in window["needs"]
                     for i,query in enumerate([self.needs[key]["query"], *self.needs[key].get("variants", [])])]
        key, result = self.predict(video, window["start"], window["end"], fps, questions)
        record = result["record"]
        # A sparse MP4's final packet can extend its header by up to one sample period.
        bounds = [[a,min(b,window["end"]-window["start"])] for a,b in record["score_bounds"]]
        if any(b <= a for a,b in bounds):
            raise ValueError("Sampled score cells extend wholly outside the requested window")
        by_id = {q["question"]["id"]: q["output"]["probabilities"] for q in result["queries"]}
        cells = []
        for i in range(len(record["score_bounds"])):
            times = [window["start"]+min(2*i+j,record["frames"]-1)/fps for j in [0,1]]
            cells.append(any(lo-1e-6 <= t < hi-1e-6 for t in times for lo,hi in black_ranges))
        rows = []
        for need_id in window["needs"]:
            vectors = [v for q,v in by_id.items() if q.startswith(need_id+"-v")]
            probabilities = [max(values) for values in zip(*vectors)]
            if len(probabilities) != len(record["score_bounds"]):
                raise ValueError("Score vector and native bounds disagree")
            row = dict(video_id=video["id"], need_id=need_id, round=round_number, window_id=key,
                start=window["start"], end=window["end"], fps=fps, probabilities=probabilities,
                bounds=bounds, black=cells, frames=record["frames"], audit=audit)
            rows.append(row)
            query_hash = digest([self.needs[need_id]["query"], self.needs[need_id].get("variants", [])])
            self.db.execute("DELETE FROM scores WHERE video_id=? AND query_hash=? AND round=? AND window_id=?",
                (video["id"],query_hash,-3 if audit else round_number,key))
            self.db.executemany("INSERT OR REPLACE INTO scores VALUES(?,?,?,?,?,?,?)", [
                (video["id"], query_hash, -3 if audit else round_number, window["start"]+a, window["start"]+b, p, key)
                for (a,b),p in zip(bounds, probabilities)])
        self.db.commit()
        self.windows.extend(rows)
        return rows

    def candidate_ranges(self, row, black):
        spans = runs(row["probabilities"], row["bounds"], .5, row["start"], row["black"])
        result = []
        for span in spans:
            for a,b in subtract(span["start"], span["end"], black):
                if b-a < 1.5:
                    continue
                count = math.ceil((b-a)/12.)
                for i in range(count):
                    lo,hi = a+(b-a)*i/count, a+(b-a)*(i+1)/count
                    if hi-lo >= 1.5:
                        result.append(dict(start=lo, end=hi, grounding=span["mean"]))
        return result

    def confirm(self, video, need_id, a, b, grounding, purpose):
        need = self.needs[need_id]
        choices = [need["confirm"]["right"], *need["confirm"]["wrong"], "None of these."]
        random.Random(self.settings["seed"]+int(digest([video["id"],need_id,round(a,6),round(b,6)]),16)).shuffle(choices)
        options = [f"{chr(65+i)}. {text}" for i,text in enumerate(choices)]
        origin=getattr(self,'confirmation_origin',None)
        if not origin or not (origin['start']<=a+1e-6 and origin['end']>=b-1e-6 and Path(origin['path']).exists()):
            origin=next((w for w in getattr(self,'sampled_windows',{}).get(video['id'],[])
            if w['start']<=a+1e-6 and w['end']>=b-1e-6 and Path(w['path']).exists()),None)
        _, prediction = self.predict(video, a, b, 2., [dict(id=need_id, task="choice", query=need["confirm"]["question"], options=options)],sample_from=origin)
        output = prediction["queries"][0]["output"]
        right = choices.index(need["confirm"]["right"])
        probability = output["probabilities"][right]
        passed = output["answer_index"] == right and probability >= self.settings["choice_threshold"]
        return dict(id=digest([video["id"],need_id,a,b,purpose]), video_id=video["id"], need_id=need_id,
            start=a, end=b, grounding=grounding, purpose=purpose, options=options,
            probabilities=output["probabilities"], answer_index=output["answer_index"], answer=output["answer"],
            right_index=right, right=options[right], confirmation=probability, choice_pass=passed,
            score=grounding*probability, source_scope_status=scope_status(video,need),confirmation_parent=origin)

    def check_candidates(self, video, rows, black, purpose):
        for row in rows:
            for span in self.candidate_ranges(row, black):
                self.status(f"{video['id']} {purpose}: confirm {row['need_id']} {span['start']:.1f}-{span['end']:.1f}")
                candidate = self.confirm(video, row["need_id"], span["start"], span["end"], span["grounding"], purpose)
                qc_key = digest([video["id"],round(span["start"],6),round(span["end"],6),video.get("crop")])
                quality_path = self.cache/(qc_key+".qc.json")
                if quality_path.exists():
                    quality = json.loads(quality_path.read_text())
                else:
                    # Reuse the already sampled 2 fps candidate file for temporal/frozen QC.
                    identity = dict(version=1,video=video["id"],size=Path(video["path"]).stat().st_size,
                        start=round(span["start"],6),end=round(span["end"],6),fps=2.,crop=video.get("crop"),context=32768,pins=self.config["model"])
                    sampled = self.cache/(digest(identity)+".mp4")
                    quality = qc.measure(sampled)
                    save_json(quality_path, quality)
                candidate["qc"] = quality
                candidate["qc_flags"] = pool.flags_of(quality)
                candidate["passed"] = candidate["choice_pass"] and not any(flag in candidate["qc_flags"] for flag in ["black","frozen"]) and candidate["source_scope_status"] != "conflict"
                candidate["handles"] = next((r for r in subtract(max(0,candidate['start']-2),min(video['probe']['duration'],candidate['end']+2),black)
                    if r[0] <= candidate['start']+1e-6 and r[1] >= candidate['end']-1e-6), [candidate['start'],candidate['end']])
                self.candidates.append(candidate)

    def rounds(self, video, black):
        duration = video["probe"]["duration"]
        first = 3 if duration < self.settings["skip_round2_under_seconds"] else 2 if duration < self.settings["skip_round1_under_seconds"] else 1
        windows = [dict(start=0., end=duration, needs=video["needs"])]
        coarse = {key: [] for key in video["needs"]}
        for number in range(first,4):
            windows = merge_windows(windows, duration, self.settings["window_seconds"][number-1])
            upcoming = []
            for window in windows:
                self.status(f"{video['id']} round {number}: {window['start']:.1f}-{window['end']:.1f}; {len(window['needs'])} needs")
                rows = self.score_window(video,window,number,black)
                if number == 3:
                    self.check_candidates(video,rows,black,"main")
                    continue
                padding = self.settings["padding_seconds"][number-1]
                for row in rows:
                    for span in runs(row["probabilities"],row["bounds"],self.settings["thresholds"][number-1],row["start"],row["black"]):
                        a,b = max(0,span["start"]-padding),min(duration,span["end"]+padding)
                        upcoming.append(dict(start=a,end=b,needs=[row["need_id"]]))
            if number == 1:
                retained=merge_windows(upcoming,duration,self.settings["window_seconds"][1])
                coarse={key:union([[w['start'],w['end']] for w in retained if key in w['needs']]) for key in video['needs']}
            windows = upcoming
        return {key:union(ranges) for key,ranges in coarse.items()}

    def audit(self, video, black, stretches, coarse):
        rows = []
        for a,b in stretches:
            self.status(f"{video['id']} independent 2 fps miss audit: {a:.1f}-{b:.1f}")
            rows.extend(self.score_window(video,dict(start=a,end=b,needs=video["needs"]),3,black,audit=True))
        prior = len(self.candidates)
        self.check_candidates(video,rows,black,"miss_audit")
        for candidate in self.candidates[prior:]:
            dropped = subtract(candidate["start"],candidate["end"],coarse[candidate["need_id"]])
            candidate["coarse_dropped"] = dropped
            candidate["coarse_dropped_seconds"] = sum(b-a for a,b in dropped)

    def representatives(self, videos):
        for need_id,need in self.needs.items():
            if need.get("manual"):
                continue
            for number,threshold in enumerate(self.settings["thresholds"],1):
                cells = []
                for row in self.windows:
                    if row["need_id"] != need_id or row["round"] != number or row["audit"]:
                        continue
                    for i,p in enumerate(row["probabilities"]):
                        if row["black"][i]:
                            continue
                        a,b = row["bounds"][i]
                        cells.append(dict(video_id=row["video_id"], need_id=need_id, round=number,
                            start=row["start"]+a, end=row["start"]+b, probability=p, fps=row["fps"],
                            frame_times=[row["start"]+min(2*i+j,row["frames"]-1)/row["fps"] for j in [0,1]]))
                cells.sort(key=lambda c:(c["video_id"],c["start"],c["end"]))
                above = [c for c in cells if c["probability"] >= threshold]
                below = sorted([c for c in cells if c["probability"] < threshold],key=lambda c:-c["probability"])
                chosen = [("random above",c) for c in random.Random(self.settings["seed"]+number+int(digest(need_id),16)).sample(above,min(3,len(above)))]
                chosen += [("nearest below",c) for c in below[:3]]
                for kind,cell in chosen:
                    cell.update(kind=kind, threshold=threshold, context=32768)
                    if need.get("hard"):
                        video = videos[cell["video_id"]]
                        a,b = cell["start"],min(video["probe"]["duration"],cell["end"])
                        if b-a < .5:
                            a=max(0,min(a,video["probe"]["duration"]-1.5))
                            b=min(video["probe"]["duration"],max(b,a+1.5))
                        self.status(f"Review choice: {need_id}, round {number}, {cell['video_id']} {a:.1f}")
                        cell["choice"] = self.confirm(video,need_id,a,b,cell["probability"],"representative")
                    self.representative.append(cell)

    def run(self):
        self.status("Waiting for background proxy downloads")
        while True:
            report = json.loads((self.folder/"download-report.json").read_text(encoding="utf-8"))
            if report["status"] == "complete":
                break
            time.sleep(5)
        videos = {v["id"]:v for v in report["videos"] if v["status"] == "ready"}
        if not videos:
            raise RuntimeError("No source proxies are available")
        long_sources = sorted([v for v in videos.values() if v["probe"]["duration"] >= 1800],key=lambda v:(-v["probe"]["duration"],v["id"]))[:2]
        if len(long_sources) < 2:
            long_sources = sorted([v for v in videos.values() if v["probe"]["duration"] >= 300],key=lambda v:(-v["probe"]["duration"],v["id"]))[:2]
        audit_plan = {v["id"]:[[max(0,min(v['probe']['duration']-120,v['probe']['duration']*f)),max(0,min(v['probe']['duration']-120,v['probe']['duration']*f))+120] for f in [.10,.50,.85]] for v in long_sources}
        audit_path = self.folder/"miss-audit-plan.json"
        if audit_path.exists():
            audit_plan = json.loads(audit_path.read_text())["sources"]
        else:
            save_json(audit_path,dict(created_before_coarse=time.time(), sources=audit_plan,
                selection="Two longest available distinct sources; fixed 10%, 50%, 85% starts; 120s each; independent of scores", required_sources=2))
        self.start_worker()
        for video in sorted(videos.values(),key=lambda v:(len(v['needs']),v['probe']['duration'],v['id'])):
            self.status(video["id"]+": detect black spans")
            try:
                black = self.black_ranges(video)
                video["black_ranges"] = black
                coarse = self.rounds(video,black)
                save_json(self.folder/"coarse"/(video["id"]+".json"), coarse)
                if video["id"] in audit_plan:
                    self.audit(video,black,audit_plan[video["id"]],coarse)
                self.state.setdefault("completed_videos",[]).append(video["id"])
            except Exception as exc:
                if "out of memory" in str(exc).lower() or (self.tasks/"fatal.json").exists():
                    raise
                self.state.setdefault("failed_videos",[]).append(dict(id=video["id"],error=str(exc),traceback=traceback.format_exc()))
                self.status(video["id"]+": failed: "+str(exc))
            save_json(self.folder/"candidates.json", self.candidates)
        self.representatives(videos)
        save_json(self.folder/"representatives.json",self.representative)
        save_json(self.folder/"candidates.json",self.candidates)
        save_json(self.folder/"timing-report.json",self.timings)
        save_json(self.folder/"score-windows.json",self.windows)
        # The existing Windows baseline already supplies Pillow; its environment stays untouched.
        review_python = Path.home()/"AppData/Local/SpearFia/cache/videojev/venv-win/Scripts/python.exe"
        command([str(review_python),str(Path(__file__).with_name("stage3_review.py")),"--project",str(self.project)],3600)
        audit_report=json.loads((self.folder/"miss-audit-report.json").read_text(encoding="utf-8"))
        self.state["status"] = "stage3_gate_ready" if audit_report["gate_complete"] else "stage3_gate_incomplete"
        self.status("Stage 3 checks finished; no assignment performed")


def run(project):
    indexer = Indexer(project)
    try:
        indexer.run()
    except Exception as exc:
        indexer.state.update(status="failed",error=str(exc),traceback=traceback.format_exc())
        indexer.status("Failed; inspect index-status.json")
        raise
    finally:
        if indexer.worker:
            (indexer.tasks/"stop").touch()
            try:
                indexer.worker.wait(timeout=30)
            except subprocess.TimeoutExpired:
                indexer.worker.terminate()
        indexer.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    run(parser.parse_args().project)
