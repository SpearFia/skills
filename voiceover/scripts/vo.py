"""Generate one voiceover file per script section with VoiceStudio's local API.

Usage:
  python vo.py [--project DIR] [--sections 1,3-5] [--profile-id ID] [--instruct TEXT]
               [--language Auto] [--speed 1.0] [--steps 32] [--force] [--dry-run]
  python vo.py --self-test

Reads the sections from `spearfia sections` (the real script parser), sends each
section's VO lines to VoiceStudio's POST /generate, and saves
<project>/A-roll/voiceover/<NN>_<slug>.wav. Existing files are kept unless --force, so a
long script can be resumed. Writes <project>/media/vo.json (files, durations) and prints
the links_add payload that links each file to its section's first VO line.

VoiceStudio must be open (its backend listens on 127.0.0.1:3900, or OMNIVOICE_URL /
OMNIVOICE_PORT). Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPEARFIA = r"C:\dev\spearfia\spearfia\target\release\spearfia.exe"
VO_DIR = "A-roll/voiceover"


def base_url():
    url = os.environ.get("OMNIVOICE_URL", "").strip().rstrip("/")
    return url or f"http://127.0.0.1:{os.environ.get('OMNIVOICE_PORT', '3900')}"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "section"


def pick(spec, available):
    if not spec:
        return available
    wanted = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        wanted.update(range(int(a), int(b or a) + 1))
    return [i for i in available if i in wanted]


def load_sections(project, spearfia):
    out = subprocess.run([spearfia, "sections", str(project)], capture_output=True, text=True,
                         check=False)
    if out.returncode:
        raise SystemExit(f"spearfia sections failed: {out.stderr.strip() or out.stdout.strip()}")
    return json.loads(out.stdout)["sections"]


def generate(url, text, args):
    form = {"text": text, "language": args.language, "speed": str(args.speed),
            "num_step": str(args.steps)}
    if args.profile_id:
        form["profile_id"] = args.profile_id
    if args.instruct:
        form["instruct"] = args.instruct
    req = urllib.request.Request(f"{url}/generate", data=urllib.parse.urlencode(form).encode(),
                                 headers={"X-VoiceStudio-CSRF": "1"}, method="POST")
    # An hour of narration in one section can take a while to render.
    with urllib.request.urlopen(req, timeout=3600) as r:
        body = r.read()
        duration = r.headers.get("X-Audio-Duration")
    if body[:4] != b"RIFF":
        raise RuntimeError(f"VoiceStudio returned {len(body)} bytes that aren't a WAV file")
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = None
    return body, duration


def run(args):
    project = Path(args.project).resolve()
    url = args.url or base_url()
    sections = [s for s in load_sections(project, args.spearfia) if s["lines"]]
    chosen = pick(args.sections, [s["index"] for s in sections])
    if not args.dry_run:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=10).read()
        except (urllib.error.URLError, OSError) as e:
            raise SystemExit(f"VoiceStudio isn't answering at {url} ({e}). Open the app first.")
    out_dir = project / VO_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project / "media" / "vo.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    links, failed = [], []
    for s in sections:
        if s["index"] not in chosen:
            continue
        name = f"{s['index']:02d}_{slug(s['title'])}.wav"
        rel = f"{VO_DIR}/{name}"
        first = s["lines"][0]
        text = "\n".join(line["text"] for line in s["lines"])
        entry = {"section": s["index"], "title": s["title"], "file": rel, "line": first["line"],
                 "quote": first["text"], "words": s["words"]}
        if args.dry_run:
            print(f"would generate {rel} ({s['words']} words)")
        elif (out_dir / name).exists() and not args.force:
            print(f"kept {rel}")
        else:
            try:
                body, duration = generate(url, text, args)
            except (urllib.error.URLError, OSError, RuntimeError) as e:
                failed.append({"section": s["index"], "error": str(e)})
                print(f"FAILED {rel}: {e}", file=sys.stderr)
                continue
            (out_dir / name).write_bytes(body)
            entry["duration"] = duration
            print(f"wrote {rel} ({duration or '?'} s)")
        manifest[str(s["index"])] = {**manifest.get(str(s["index"]), {}), **entry}
        links.append({"line": first["line"], "quote": first["text"], "media": rel})
    if not args.dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(json.dumps({"links_add": {"links": links}, "failed": failed}, indent=2))
    return 1 if failed else 0


def self_test():
    """Fake VoiceStudio and `spearfia sections`, then check files, manifest and payload."""
    calls = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.headers.get("X-VoiceStudio-CSRF"),
                          urllib.parse.parse_qs(body.decode())))
            wav = b"RIFF" + b"\0" * 40
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("X-Audio-Duration", "2.5")
            self.end_headers()
            self.wfile.write(wav)

    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sections = {"sections": [
        {"index": 1, "title": "Cold open!", "line": 1, "words": 4,
         "lines": [{"line": 2, "text": "Could Harry beat Thanos?", "words": 4}]},
        {"index": 2, "title": "Empty", "line": 4, "words": 0, "lines": []},
        {"index": 3, "title": "Round one", "line": 5, "words": 5,
         "lines": [{"line": 6, "text": "The wand chose.", "words": 3},
                   {"line": 7, "text": "Then war.", "words": 2}]},
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fake = tmp / "fake_spearfia.py"
        fake.write_text(f"print({json.dumps(json.dumps(sections))})\n", "utf-8")
        launcher = tmp / ("spearfia.cmd" if os.name == "nt" else "spearfia")
        launcher.write_text(f'@"{sys.executable}" -I "{fake}"\n' if os.name == "nt"
                            else f'#!/bin/sh\nexec "{sys.executable}" -I "{fake}"\n', "utf-8")
        launcher.chmod(0o755)
        project = tmp / "ep"
        args = argparse.Namespace(project=str(project), spearfia=str(launcher), sections="3",
                                  url=f"http://127.0.0.1:{server.server_port}", profile_id="v1",
                                  instruct=None, language="Auto", speed=1.0, steps=32,
                                  force=False, dry_run=False)
        assert run(args) == 0
        wav = project / VO_DIR / "03_round-one.wav"
        assert wav.read_bytes()[:4] == b"RIFF"
        assert not (project / VO_DIR / "01_cold-open.wav").exists()
        csrf, form = calls[0]
        assert csrf == "1" and form["text"] == ["The wand chose.\nThen war."], calls
        assert form["profile_id"] == ["v1"], form
        manifest = json.loads((project / "media" / "vo.json").read_text("utf-8"))
        assert manifest["3"]["duration"] == 2.5 and manifest["3"]["line"] == 6, manifest
        # A second run keeps the existing file instead of regenerating it.
        assert run(args) == 0 and len(calls) == 1
    server.shutdown()
    print("self-test passed")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--project", default=r"D:\SpearFia\current")
    p.add_argument("--spearfia", default=SPEARFIA)
    p.add_argument("--sections", help="e.g. 1,3-5 (default: all)")
    p.add_argument("--url", help="VoiceStudio backend (default: OMNIVOICE_URL or :3900)")
    p.add_argument("--profile-id", help="saved voice profile (default: VoiceStudio's default)")
    p.add_argument("--instruct", help="style, e.g. 'energetic narrator'")
    p.add_argument("--language", default="Auto")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--steps", type=int, default=32, help="8 draft, 16 balanced, 32 quality")
    p.add_argument("--force", action="store_true", help="regenerate existing files")
    p.add_argument("--dry-run", action="store_true")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
