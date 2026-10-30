# SPDX-License-Identifier: MIT OR Apache-2.0
"""Check sampled frame identities against a uniquely burned source timecode."""
import json
import re
import subprocess
import sys
from pathlib import Path


def selected_frames(log):
    before, after = {}, []
    for line in log.splitlines():
        match = re.search(r"Parsed_showinfo_(\d+).*?pts_time:([0-9.e+-]+).*? checksum:([0-9A-F]+)", line)
        if not match:
            continue
        index, stamp, checksum = match.groups()
        if index == "0":
            if checksum in before:
                raise ValueError("Reference frames must have unique timecodes/checksums")
            before[checksum] = float(stamp)
        else:
            after.append((float(stamp), checksum))
    if not after or any(checksum not in before for _, checksum in after):
        raise ValueError("No complete before/after frame identity mapping")
    return [dict(output_time=t, selected_time=before[checksum], error=before[checksum]-t)
            for t, checksum in after]


def prepare(source, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    reference = output_dir / "alignment-reference.mp4"
    burn = (r"setpts=PTS+240/TB,drawtext=fontfile='C\:/Windows/Fonts/consola.ttf':"
            r"text='SRC %{pts\:hms}':x=8:y=8:fontcolor=white:fontsize=56:"
            r"box=1:boxcolor=black@0.9,setpts=PTS-STARTPTS")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "240", "-t", "60",
        "-i", str(source), "-an", "-vf", burn, "-fps_mode", "passthrough", "-c:v", "libx264",
        "-preset", "ultrafast", "-g", "1", str(reference)], check=True)
    first = subprocess.run(["ffmpeg", "-hide_banner", "-ss", "240", "-i", str(source),
        "-vf", "showinfo", "-frames:v", "1", "-an", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    origin = 240 + float(re.search(r"Parsed_showinfo_0.*?pts_time:([0-9.e+-]+)", first.stderr).group(1))
    results = []
    for fps in [0.2, 0.5, 2.0]:
        for rounding in ["near", "up"]:
            path = output_dir / f"alignment-{fps}-{rounding}.mp4"
            filters = f"showinfo,fps={fps}:start_time=0:round={rounding},trim=duration=30,showinfo"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y", "-ss", "17.25", "-t", "30",
                "-i", str(reference), "-an", "-vf", filters, "-c:v", "libx264", "-preset", "ultrafast",
                "-g", "1", "-t", "30", str(path)]
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
            frames = selected_frames(run.stderr)
            results.append(dict(fps=fps, rounding=rounding, path=str(path), filename=path.name,
                source_start=origin+17.25, reference_source_start=origin,
                frames=frames, max_abs_error=max(abs(f["error"]) for f in frames)))
            print(f"{fps} fps / {rounding}: max error {results[-1]['max_abs_error']:.6f}s", flush=True)
    (output_dir / "alignment-inputs.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
