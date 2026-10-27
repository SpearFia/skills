# SPDX-License-Identifier: MIT OR Apache-2.0
"""Transcribe a Spear Fia project's voiceover files with word timestamps, for exact timing.

Usage:
  <whisper python> vo_words.py --project P [--model small] [--device auto|cuda|cpu]
  <whisper python> vo_words.py --self-test

Writes P/media/vo-words.json: {"<file>": {"sha256", "model", "words": [[text, start_s, end_s], ...]}}
for every audio file in A-roll/voiceover. Files whose hash is unchanged are skipped, so rerun it
after re-recording a section. `spearfia push` aligns these words to the script.
Needs faster-whisper (installed in D:/SpearFia/tools/whisper, with the nvidia-cublas/cudnn wheels for the GPU).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(name, device):
    import os
    import numpy as np
    from faster_whisper import WhisperModel
    nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for d in nvidia.glob("*/bin"):  # CUDA DLLs from the nvidia-* wheels
        os.add_dll_directory(str(d))
        os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"
    if device in ("auto", "cuda"):
        try:
            m = WhisperModel(name, device="cuda", compute_type="float16")
            list(m.transcribe(np.zeros(16000, np.float32))[0])  # CUDA libraries load lazily
            return m
        except Exception as e:  # missing CUDA libraries: fall back to the CPU
            if device == "cuda":
                raise
            print(f"cuda unavailable ({e}); using cpu", file=sys.stderr)
    return WhisperModel(name, device="cpu", compute_type="int8")


def decode(path):
    """16 kHz mono float32 via ffmpeg (faster-whisper's PyAV decoder breaks on newer PyAV)."""
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def words_of(model, path):
    segments, _ = model.transcribe(decode(path), language="en", word_timestamps=True, vad_filter=False)
    return [[w.word.strip(), round(w.start, 3), round(w.end, 3)] for s in segments for w in s.words]


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project")
    p.add_argument("--model", default="small")
    p.add_argument("--device", default="auto")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    project = Path(a.project)
    out = project / "media" / "vo-words.json"
    done = json.loads(out.read_text("utf-8")) if out.exists() else {}
    files = sorted(f for f in (project / "A-roll" / "voiceover").iterdir() if f.suffix.lower() in AUDIO)
    todo = [f for f in files if done.get(f.relative_to(project).as_posix(), {}).get("sha256") != sha(f)]
    model = load_model(a.model, a.device) if todo else None
    for f in todo:
        rel = f.relative_to(project).as_posix()
        done[rel] = {"sha256": sha(f), "model": a.model, "words": words_of(model, f)}
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(done), "utf-8")  # save after each file so a stop loses little
        print(f"{rel}: {len(done[rel]['words'])} words")
    print(f"{len(files)} files, {len(todo)} transcribed, words in {out}")


def self_test():
    import tempfile
    import wave
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp)
        vo = proj / "A-roll" / "voiceover"
        vo.mkdir(parents=True)
        with wave.open(str(vo / "01.wav"), "wb") as w:  # silence: zero words, but a valid entry
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(b"\0\0" * 16000)
        main(["--project", str(proj), "--model", "tiny", "--device", "cpu"])
        d = json.loads((proj / "media" / "vo-words.json").read_text("utf-8"))
        assert list(d) == ["A-roll/voiceover/01.wav"] and d["A-roll/voiceover/01.wav"]["sha256"]
        main(["--project", str(proj), "--model", "tiny", "--device", "cpu"])  # unchanged: skipped
    print("self-test passed")


if __name__ == "__main__":
    main(sys.argv[1:])
