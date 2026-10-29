---
name: audio-gen
description: Generate music beds and sound effects for a Spear Fia video with Stable Audio 3 through the local ComfyUI API, following the channel's sound style, then link them so they land on their own tracks (music on A2, SFX on A3) in the FilmCraft review timeline. Use for "make the music", "add sound effects", "score chapter 2", or the music/SFX stage of the production pipeline.
---

# Music and sound effects

Plan, generate and link a video's music beds and sound effects. Generation runs on the
creator's ComfyUI (Stable Audio 3 Medium); placement uses Spear Fia links on folders with
the `music` and `sfx` roles, which the FilmCraft push puts on tracks A2 and A3 without
touching the voiceover timing on A1.

## Coordinated production

When Spear Fia exposes `jobs_status`, use its durable runner instead of starting the
manual helper below. Read the current stage and plan revision. Plan new
ComfyUI API workflows with `jobs_plan`: set the current `audio-sample` or `audio` stage,
dependencies, exact output node/index, project media path, role and narration anchor.
Use `jobs_run` for that stage. Its saved prompt ID survives restarts; library files
still need source/QC verification. Wait for sample review before scoring the remainder.

Save actual `voice_db`, `music_db`, `sfx_db`, fades, duck dB, attack and release in the
execution style through `style_save`, using `jobs_status.style_revision`. Assembly
applies these values to FilmCraft gains and automation. A2/A3 placement alone is not
a completed mix. Inspect the saved review for clipping, audibility and cue placement.

## Before starting

1. `project_context`: the script must be approved. Read `channel_read` (style.md § Sound
   and § Editing: music genre and mood per section type, bed level, SFX density and
   triggers, silence) and the Visual Script (`visuals_export` cue-sheet) for reveals,
   transitions and action beats.
2. `media_list` must show folders with roles `music` and `sfx` (new projects have `Music/`
   and `SFX/`). If missing, ask the creator to add them in the Media stage with those
   roles. Don't put audio in other folders: they link as picture.
3. ComfyUI must be running (`http://127.0.0.1:8188/system_stats`, or `COMFYUI_URL`).
4. Library: `D:\SpearFia\library\audio\` (or the path in the channel's `tools.md`).

## Plan

Write `media/audio-plan.md` before generating:

- **Music palette.** An hour-long video doesn't need an hour of unique music. Choose 4–8
  moods the channel uses (from style.md), and make 2 beds of 90–150 s per mood. Assign a
  mood to each section; consecutive sections may share a bed.
- **Music changes.** One music link per change point, on the first words of the section
  (or beat) where the mood changes. A bed runs until the next music link or the end of
  the narration; FilmCraft review shows where a bed runs out (a "short" issue), and the
  editor loops or extends it there.
- **SFX.** Only where the channel's style uses them: hits on reveals, whooshes on
  transitions, risers before verdicts, meme stings for jokes. Follow the DNA's density
  (for example "about one per 20 s in the body"). Omitting SFX is a valid choice.
- **Reuse first.** Search `library.jsonl` for a fitting bed or effect before generating.

## Write prompts

Stable Audio responds to concrete, production-style descriptions. No lyrics or vocals
for beds under narration.

- **Music:** genre, mood, tempo (BPM), key instruments, texture, and "instrumental, no
  vocals, steady, loopable, suitable under voiceover". Example: "Dark orchestral hybrid
  underscore, 90 BPM, low strings ostinato, soft taiko pulses, distant brass swells,
  tense and building, instrumental, no vocals, steady, suitable under voiceover".
- **SFX:** one event, its materials and its tail. Example: "single deep cinematic
  impact hit with sub boom and short metallic tail, dry, no music".
- Length: SFX 1–4 s, risers 3–8 s, beds 90–150 s.

## Generate

One clip:

```text
python <skill>/scripts/comfy_audio.py --prompt "<prompt>" --seconds 120 --out "<library>\music\tense-orchestral-a.wav"
```

Many: write a jobs file (`[{"prompt", "seconds", "out", "seed"?}]`) and run
`--jobs jobs.json`. Existing outputs are kept unless `--force`, so runs resume. The
script prints each file's seed and actual length; record them.

Listen to (or have the creator listen to) at least one bed per mood and one SFX before
generating the rest. Regenerate with another seed rather than accepting a bad take.

Optional, for consistent levels before linking:

```text
ffmpeg -i in.wav -af loudnorm=I=-20:TP=-2:LRA=11 out.wav   (beds)
ffmpeg -i in.wav -af loudnorm=I=-16:TP=-1:LRA=11 out.wav   (SFX)
```

## Store and link

1. Library: keep the file and append to `<library>/audio/library.jsonl`:
   `{"file", "kind": "music"|"sfx", "mood", "prompt", "seed", "seconds", "used_in", "added"}`.
2. Project: copy into `Music/` or `SFX/` (`<section>_<mood>.wav`, `<cue>_<effect>.wav`).
3. Link with `links_add`: music on the first words of its section or beat; SFX on the
   exact words where it should hit. Role and track follow the folder.
4. Record each file in `media/manifest.jsonl` (file, kind, prompt, seed, risk class
   `generated`).

## Report

Per section: mood and bed used, SFX placed, anything left unscored, and total generation
time. Note beds shorter than their span (they'll show as "short" after the push).

## Limits

- Prompt rewriting with the workflow's Qwen step is skipped; the agent writes final prompts.
- Mixing (ducking under VO, fades) happens in FilmCraft, not here.

`jobs_run` is asynchronous over MCP/HTTP. Poll `jobs_status` until `running` is false,
inspect every requested job and worker error, then verify the expected files and links.
A returned `started` acknowledgement does not complete a production stage.
