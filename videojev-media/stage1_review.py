# SPDX-License-Identifier: MIT OR Apache-2.0
"""Render scored input-frame pairs, confidence plots and per-query review tables."""
import html
import io
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def stamp(seconds):
    return f"{int(seconds)//60:02}:{seconds%60:06.3f}"


def frame(path, seconds):
    data = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
        "-i", str(path), "-frames:v", "1", "-vf", "scale=320:-1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"])
    return Image.open(io.BytesIO(data)).convert("RGB")


def plot(case):
    colors = ["#1864ab", "#d97706", "#2b8a3e", "#0c8599", "#c92a2a"]
    parts = ['<svg viewBox="0 0 1100 260" role="img" aria-label="Grounding probabilities over source time">',
             '<rect width="1100" height="260" fill="white"/>']
    for p in [0, .5, 1]:
        y = 195-160*p
        parts.append(f'<path d="M50,{y} H1070" stroke="#bbb" stroke-dasharray="4 4"/><text x="5" y="{y+5}">{p:.1f}</text>')
    for i in range(5):
        relative = case["duration"]*i/4
        parts.append(f'<text x="{50+1020*i/4}" y="225" text-anchor="middle">{stamp(case["source_start"]+relative)}</text>')
    for index, query in enumerate(case["queries"]):
        points = " ".join(f"{50+1020*t/case['duration']:.2f},{195-160*p:.2f}"
            for t,p in zip(case["record"]["score_times"],query["probabilities"]))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[index]}" stroke-width="2"/>')
        parts.append(f'<text x="{50+index*205}" y="252" fill="{colors[index]}">{html.escape(query["question"]["id"])}</text>')
    return "".join(parts)+"</svg>"


def render(result, manifest, alignment, output):
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    sources = {s["id"]:s for s in manifest["sources"]}
    pictures = {}
    document = ["<!doctype html><meta charset='utf-8'><title>Stage 1 accuracy review</title>",
        "<style>body{font:16px system-ui;max-width:1500px;margin:32px auto;padding:0 16px;color:#17202a}img,svg{max-width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccc;text-align:left}summary{font-size:22px;font-weight:600;padding:20px 0;cursor:pointer}a{color:#1864ab}.note{padding:16px;background:#fff3bf}code{background:#eee}</style>",
        "<h1>Stage 1: inspect the model's actual sampled pictures</h1>",
        "<p class='note'>Each row shows the three strongest non-adjacent score cells, with both input frames in each cell. These pictures are shown even when no score reaches 0.50. A giraffe is the deliberately absent control. Scores are model confidence, not verified accuracy. Frame times use the corrected sampler and are within source-frame rounding.</p>"]
    markdown = ["# Stage 1 per-query measurements", "", "Scores are probabilities. Peak columns are PyTorch allocated/reserved MiB. Positive seconds use p ≥ 0.50, a diagnostic starting threshold, not a validated acceptance rule.", ""]
    for case in result["cases"]:
        key = f"{case['source']}-{case['context']}"
        document.append(f"<details open><summary>{html.escape(case['source'])} — context {case['context']:,}</summary>")
        markdown += [f"## {case['source']}, context {case['context']:,}", ""]
        if case["status"] != "complete":
            document.append("<p>FAILED: "+html.escape(case["error"])+"</p></details>")
            markdown += ["Failed: "+case["error"], ""]
            continue
        source = sources[case["source"]]
        record = case["record"]
        geometry = f"{record['grid_thw'][2]*16}×{record['grid_thw'][1]*16}"
        label = f"source {stamp(case['source_start'])}–{stamp(case['source_start']+case['duration'])}; {case['fps']} fps; model image {geometry}; {record['tokens']:,} video tokens"
        budget = f"Image-preprocessing budget {case['preprocess_context']:,}; longest padded question {case['budget_attempts'][-1]['longest_padded_prompt']:,} tokens within language context {case['context']:,}."
        document.append("<p>"+html.escape(label+". "+budget)+"</p>")
        markdown += [label+f". Preprocess {case['prepare_seconds']:.3f} s; encode {case['encode_seconds']:.3f} s; features retained only in RAM: {case['feature_bytes']/2**20:.2f} MiB. "+budget, ""]
        sheet = Image.new("RGB", (1440, 90+len(case["queries"])*225), "#101820")
        draw = ImageDraw.Draw(sheet)
        draw.text((12,10), f"{key} | {label}", font=font, fill="white")
        draw.text((12,40), "Top 3 distinct cells, 2 model-input frames per cell | raw source frames shown; geometry above records model resolution", font=small, fill="#d8e1eb")
        document.append("<table><tr><th>Query</th><th>Max / mean / p95</th><th>Seconds ≥ .50</th><th>Query time</th><th>Peak allocated / reserved MiB</th><th>Source at maximum</th></tr>")
        markdown += ["| Query | Max | Mean | p95 | Seconds ≥ .50 | Query s | Peak allocated / reserved MiB |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row_index, query in enumerate(case["queries"]):
            summary = query["summary"]
            q = query["question"]
            y = 90+row_index*225
            color = "#ff9090" if q["id"] == "absent" else "white"
            draw.text((12,y), f"{q['id']}: {q['query']}  | max {summary['max']:.4f} | {summary['seconds_ge_050']:.1f}s at p>=0.50", font=font, fill=color)
            for rank, cell in enumerate(summary["top_cells"]):
                bounds = record["score_bounds"][cell]
                for pair in [0,1]:
                    number = min(2*cell+pair,record["frames"]-1)
                    cache_key = (case["source"],number)
                    if cache_key not in pictures:
                        pictures[cache_key] = frame(source["path"],number/case["fps"])
                    thumbnail = ImageOps.pad(pictures[cache_key],(240,135),color="black")
                    x = (2*rank+pair)*240
                    sheet.paste(thumbnail,(x,y+34))
                    draw.text((x+5,y+173),f"input {stamp(case['source_start']+number/case['fps'])}",font=small,fill="white")
                    draw.text((x+5,y+194),f"cell {stamp(case['source_start']+bounds[0])}–{stamp(case['source_start']+bounds[1])} p={query['probabilities'][cell]:.4f}",font=small,fill="#d8e1eb")
            maximum = max(range(len(query["probabilities"])),key=query["probabilities"].__getitem__)
            at = case["source_start"]+record["score_times"][maximum]
            url = source["url"]+f"&t={int(at)}s"
            document.append(f"<tr><td>{html.escape(q['query'])}</td><td>{summary['max']:.4f} / {summary['mean']:.4f} / {summary['p95']:.4f}</td><td>{summary['seconds_ge_050']:.2f}</td><td>{query['seconds']:.3f} s</td><td>{query['peak_allocated_mib']:.1f} / {query['peak_reserved_mib']:.1f}</td><td><a href='{html.escape(url,quote=True)}'>{stamp(at)}</a></td></tr>")
            markdown.append(f"| {q['query']} | {summary['max']:.4f} | {summary['mean']:.4f} | {summary['p95']:.4f} | {summary['seconds_ge_050']:.2f} | {query['seconds']:.3f} | {query['peak_allocated_mib']:.1f} / {query['peak_reserved_mib']:.1f} |")
        filename = key+".jpg"
        sheet.save(output/filename,quality=92)
        document.append(f"</table>{plot(case)}<a href='{filename}'><img src='{filename}' alt='{html.escape(key)} contact sheet'></a></details>")
        markdown += ["",f"Contact sheet: `{output/filename}`.", ""]
    sheet = Image.new("RGB",(1440,6*205+40),"#101820")
    draw = ImageDraw.Draw(sheet)
    draw.text((10,8),"Timestamp alignment: burned SRC time is the selected original picture; caption is the model input time + source offset",font=font,fill="white")
    for row,test in enumerate(alignment):
        y=40+row*205
        draw.text((10,y),f"{test['fps']} fps / round={test['rounding']} | max frame error {test['max_abs_error']:.6f}s",font=font,fill="white")
        for i, selected in enumerate(test["frames"][:6]):
            image = ImageOps.pad(frame(test["path"], selected["output_time"]),(240,135),color="black")
            sheet.paste(image,(240*i,y+28))
            draw.text((240*i+5,y+168),"expected "+stamp(test["source_start"]+selected["output_time"]),font=small,fill="white")
    sheet.save(output/"alignment.jpg",quality=95)
    document.append("<h2>Burned-timecode alignment</h2><a href='alignment.jpg'><img src='alignment.jpg' alt='Default and corrected frame sampling compared against burned source timecodes'></a>")
    (output/"review.html").write_text("\n".join(document),encoding="utf-8")
    (output/"measurements.md").write_text("\n".join(markdown),encoding="utf-8")


if __name__ == "__main__":
    render(json.loads(Path(sys.argv[1]).read_text()),json.loads(Path(sys.argv[2]).read_text()),
           json.loads(Path(sys.argv[3]).read_text()),Path(sys.argv[4]))
