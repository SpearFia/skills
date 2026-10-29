---
name: voiceover
description: Generate a Spear Fia video's narration with the local VoiceStudio app, one audio file per script section, then link each file to its section so timelines use the real VO length. Use for "generate the voiceover", "make the VO", "re-record chapter 3", or the voiceover stage of the production pipeline.
---

# Voiceover

Turn the approved script into narration files with VoiceStudio (local API), one WAV per
`##` section, and link each file to its section in Spear Fia. Once linked, Spear Fia's
timelines, the Visual Script and the FilmCraft push use the recorded lengths instead of
the 150-words-per-minute estimate.

## Coordinated production

When Spear Fia exposes `jobs_status`, use its durable runner instead of starting the
manual helper below. Read the current stage and plan revision. Use `voiceover_plan`
with the recorded URL, profile ID, instruction, language, speed and steps; run only
`voiceover-sample` first with `jobs_run`. Wait for the saved creator review gate before
running `voiceover`. The runner verifies the WAV and registers its narration link.
After narration, use `alignment_plan`, `jobs_run` for `word-alignment`, and
`captions_build`. Missing or reordered measured words need correction, never estimated
word timestamps.

VoiceStudio ordinary TTS has no resumable request ID. The runner saves a seed before
submission and reconciles completed takes through history. An uncertain take requires
creator inspection; restarting or retrying must not trigger another generation.

## Before starting

1. `project_context` (MCP server `spearfia`): the script must be approved. Generating
   audio from an unapproved script wastes hours of rendering; stop and say so.
2. Read the channel's `tools.md` § VoiceStudio for the voice profile ID, style
   instruction, speed and pronunciation notes. If no profile is recorded, ask the creator
   which voice to use (`list_voices` in VoiceStudio's MCP, or its app) and record it there.
3. VoiceStudio must be open. Its backend answers on `http://127.0.0.1:3900/health`
   (`OMNIVOICE_URL` or `OMNIVOICE_PORT` override it).

## Steps

1. Preview what will be generated:

   ```text
   python <skill>/scripts/vo.py --project D:\SpearFia\current --dry-run
   ```

2. Generate a short section first and listen to it (pronunciation, pace, voice):

   ```text
   python <skill>/scripts/vo.py --sections 1 --profile-id <id> --instruct "<style>"
   ```

3. Generate the rest. Existing files are kept, so an interrupted run resumes; use
   `--force` with `--sections` to redo specific sections after script fixes.
4. Link the files: pass the `links_add` payload the script prints to the `links_add` tool.
   `links_list` must show each link `linked`.
5. Word timing: `D:\SpearFia\tools\whisper\Scripts\python.exe <skill>/scripts/vo_words.py --project <P>`
   transcribes every voiceover file with word timestamps into `media/vo-words.json`
   (about a minute for 30 minutes of audio on the GPU). The FilmCraft push aligns them to the
   script so footage, edits and captions land on the spoken word. Rerun it after
   regenerating a section; unchanged files are skipped.
6. Report: sections generated, total duration (from `media/vo.json`), failures and their
   errors, and anything that sounded wrong.

The script writes to `A-roll/voiceover/` (the project's voiceover folder, so links are
audio) and records each file's section, first line and duration in `media/vo.json`.

## Fixing a section

If the creator edits a section after VO exists, regenerate just that section with
`--sections N --force`, then check `links_list`: a link whose first line changed shows
`lost`; remove it (`links_remove`) and link the new file from the printed payload.

## Limits

- `LIVE:` lines are recorded on camera and are skipped.
- One file per section. VoiceStudio splits long sections into chunks and crossfades them
  itself.
- Pronunciation fixes go in VoiceStudio (its pronunciation dictionary) or as spelling in a
  copy of the text; never edit the approved script just for pronunciation.

`jobs_run` is asynchronous over MCP/HTTP. Poll `jobs_status` until `running` is false,
inspect every requested job and worker error, then verify the expected files and links.
A returned `started` acknowledgement does not complete a production stage.
