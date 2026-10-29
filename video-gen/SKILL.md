---
name: video-gen
description: Generate seamless loop clips (picture with its own synced audio) with MiniMax H3 through the local ComfyUI API, splice them into segment videos timed to their segment audio, and render a whole multi-hour session with ffmpeg. Use for generated-video channels such as SlimeASMR-UltraLongForm, "make the loop clips", "splice segment S04", or "render the session".
---

# Generated video: loops, splices, render

For channels whose picture is generated rather than searched. The channel's guides
(style.md § Sensory spec, tools.md § MiniMax H3 Easy, production.md) say what to make;
this skill makes it. Run after the creator approves the session sheet.

## Before starting

1. `project_context`: the session sheet (script) must be approved.
2. ComfyUI is running (`http://127.0.0.1:8188/system_stats`, or `COMFYUI_URL`).
3. Media folders: `Refs/`, `Clips/Snn/`, `Segments/` (voiceover role), `Spliced/` (b-roll role).

## Working efficiently

Every tool call re-reads the whole conversation, so cost is calls × context. ASMR 001 (a
10-minute video) took 163 model calls with context growing from 78K to 200K tokens: about
25.6M input tokens, almost all of it re-reading. Fewer, larger calls matter far more than
shorter outputs.

- **Read once, read little.** The project's `channel.md` snapshot already holds every
  channel guide; read it or `spearfia channels read`, not both. Then this file and
  [references/prompting.md](references/prompting.md). Don't read the research report; grep
  one catalog family from it if you need pairing ideas.
- **One command does the production.** Write the session sheet and `media/produce.json`
  (below) in one pass, then run `produce.py` as a single background command and end your
  turn: the harness wakes you when it exits. Never wait with `sleep`, `Wait-Process`,
  `tasklist`, `wmic`, or repeated reads of a task's output. About a third of ASMR 001's calls
  were spent waiting on or inspecting running jobs.
- **Two looks only.** Run `--until first-clips`, look at `cache/first-clips.png` (the first
  clip of every segment), fix any prompt, then run again without `--until`; look at a final
  contact sheet of the render.
- **Read the summary, not logs.** `produce.py` ends with a few lines (files made, re-rolls,
  failures, loudness); `media/produce-report.json` has the detail when something failed.
- **Trust the re-rolls.** QC already retries failed seeds. Don't re-run `qc.py` by hand on
  rejected files; if a job fails all its retries, change the prompt (see the sparse-sound
  note in prompting.md), not the seed.
- **Write files with the Write tool or Python (UTF-8), never PowerShell.** A PowerShell write
  put a BOM in `project.json` and the desktop couldn't open the project. `produce.py` adds
  the media folders and their roles itself.
- **Render once.** The render normalises loudness in two passes and reports what it hit;
  don't re-render for loudness.
- **Link afterwards, in one call**, if the video will be pushed to FilmCraft: one `links_add`
  with every segment's sound, picture and bed.

## One command: produce.py

```text
python <skill>/scripts/produce.py --project <folder> --until first-clips
python <skill>/scripts/produce.py --project <folder>
```

`media/produce.json` holds every prompt; `script/script.md` holds the segment order:

```json
{"name": "asmr-002", "clips": 4, "seconds": 8,
 "segments": {"S01": {"audio": {"prompt": "TrackType: SFX, ...", "chunks": 2, "seconds": 120},
                      "ref": "<reference image prompt>", "clip": "<H3 motion-path prompt>"}},
 "beds": {"M01": {"prompt": "TrackType: SFX, soft steady rain ...", "seconds": 150}}}
```

It checks the spec against the sheet (every `VO: Snn` line has an entry and the other way
round), then makes segment audio (chunks crossfaded into `Segments/Snn.wav`) and beds, each
segment's reference image and first clip, `cache/first-clips.png`, the remaining clips,
the splices and `exports/<name>.mp4`. Seeds are stable per segment, finished files are kept
(a rerun resumes), and every file passes QC with re-rolls. A job that fails all its retries
stops the run before splicing. `--dry-run` counts what's left to make. The scripts below are
what it runs; use them directly only to redo one piece.

## Clips

```text
python <skill>/scripts/comfy_video.py --jobs jobs.json
```

Jobs: `[{"prompt", "image", "seconds", "out", "seed"?, "ref_prompt"?, "loop"?}]`. The image
is anchored at the first and last frame, so each clip loops (`"loop": false` anchors the
first frame only). A missing image with `ref_prompt` is generated first (MOSS-Image, 16:9).
Existing outputs are kept, so runs resume. Each result has its seed and generation time;
record them in `media/manifest.jsonl`.

Make the sample segment first and stop for the creator to watch and listen.

## Splice and render

```text
python <skill>/scripts/splice.py segment --clips Clips/S01 --audio Segments/S01.wav --out Spliced/S01.mp4
python <skill>/scripts/splice.py render --project <folder> --out exports/<name>.mp4
```

`segment` needs the segment audio first (stage order in production.md). Link
`Segments/Snn.wav` and `Spliced/Snn.mp4` to the segment's line with `links_add`. `render`
reads levels and fades from the `spearfia-style` block in the project's `channel.md`, dips
the picture to black between segments and movements (audio crossfades), and loops each
movement's ambient bed `Beds/Mnn.wav` (numbered by `##` order) under it when present.

## Mixing

**Mix sheet.** `media/mix.json` sets volume and EQ per segment and per layer; `render`
applies it before the final loudness pass, so changing it only needs a re-render (minutes, no
regeneration):

```json
{
  "*":   { "bed": { "db": -2 } },
  "S02": { "segment": { "db": 3, "eq": ["crisp"] }, "clip": { "eq": ["soften"] } }
}
```

- Layers: `segment` (the Stable Audio sound), `clip` (H3's own sound), `bed` (ambience).
- `db` adds to the channel level; `"*"` applies to every segment and a segment's own entry
  adds to it.
- `eq` takes presets or bands: `crisp` (+4 dB at 4.5 kHz: crunch, crackle, splash
  detail), `soften` (−4 dB at 6.5 kHz: hiss, harshness), `warm` (+3 dB at 250 Hz),
  `clean-low` (high-pass at 60 Hz), or `{"freq", "gain", "q"?}`, `{"highpass"}`,
  `{"lowpass"}`.
- Typos (unknown segment, layer or preset) stop the render rather than being ignored.

EQ can tilt the balance inside one layer but can't separate two sounds generated in the
same file. When a sound needs its own fader, generate it as its own layer.

**By hand in FilmCraft.** With `picture_db` in the channel's mix settings, `spearfia push
filmcraft` puts each layer on its own track: segment sound on A1, beds on A2, H3 clip sound
on A4. Mix with faders and FilmCraft's Parametric Equalizer, then export from FilmCraft, or
copy the settled levels into `mix.json` so later renders match (edits don't flow back to
Spear Fia yet). Linking `Segments/`, `Spliced/` and `Beds/` to their lines is required for a
push. The push doesn't loop beds, so a bed shorter than its movement shows as "short".

## Automatic QC

`comfy_video.py` runs `scripts/qc.py` on every reference image and clip, and
`audio-gen`'s `comfy_audio.py --qc` on every audio chunk. A fail is kept as
`<name>.rejected-<n>` and the next seed is tried (`--retries`, default 2). After that the job
reports an error; nothing that failed is ever used. Stable Audio chunks are turned down to a −1 dBFS
peak before QC: the model's raw output peaks at 0 dBFS, which would read as clipping.

| Asset | Check | Fails when |
| --- | --- | --- |
| Reference image | Black background | 30th-percentile brightness > 14 (navy, grey) |
| Clip | Loop seam | last→first jump > 3× the clip's normal frame step |
| Clip | Motion | mean lit-pixel change from frame 0 < 0.06 |
| Clip | Flashing | > 3 flashes in any second (WCAG 2.3.1) |
| Clip | Flicker | local frame-to-frame jitter > 2.5 (boiling grain) |
| Clip, audio | Clipping | sample peak > −0.3 dBFS |
| Clip, audio | Sudden peak | a 50 ms burst > 24 dB over the median and > −24 dBFS |
| Audio | Dropout | > 1 s of silence inside the file |
| Clip, audio | Voice | Whisper (CPU, `base`) hears > 2 confident words |

Seam and motion compare lit pixels only: SSIM over a mostly black frame stays high however
much the light moves. Thresholds live in `qc.py`'s `LIMITS`, set on the 2026-10-27 test
clips; adjust them there when a lesson says so. Run one file by hand with
`python qc.py image|clip|audio <file>`.

Still look at the contact sheet for the first clip of each segment and listen to the first
minute of each spliced segment: QC catches broken files, not boring ones. All scripts have
`--self-test`.

## Limits

- `produce.py` doesn't link files in Spear Fia; do it in one `links_add` call before a
  FilmCraft push.
- QC thresholds are calibrated on six test clips, not a full video; expect to tune them.
- The voice check is skipped (and says so) when the whisper venv isn't at `WHISPER_PYTHON`.
- A queued ComfyUI prompt is not a finished clip; only files on disk count.
