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

## Automatic QC

`comfy_video.py` runs `scripts/qc.py` on every reference image and clip, and
`audio-gen`'s `comfy_audio.py --qc` on every audio chunk. A fail is kept as
`<name>.rejected-<n>` and the next seed is tried (`--retries`, default 2). After that the job
reports an error; nothing that failed is ever used.

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

- QC thresholds are calibrated on six test clips, not a full video; expect to tune them.
- The voice check is skipped (and says so) when the whisper venv isn't at `WHISPER_PYTHON`.
- A queued ComfyUI prompt is not a finished clip; only files on disk count.
