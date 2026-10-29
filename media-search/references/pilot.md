# Media and Editing Script pilot

Licensed under MIT OR Apache-2.0.

This opt-in pilot reads an existing Spear Fia project, its Visual Script, latest timeline
plan, linked voiceover and word alignment. It does not rewrite scripts, review beats,
change production links, or modify FilmCraft projects. Output belongs in a separate folder
on the media drive. Existing `pool.py auto/commit` behavior is unchanged.

The implementation uses Python's standard library plus installed ffmpeg/ffprobe. Gemini
uses `GEMINI_API_KEY`, including the Windows user environment registry fallback. The key
is never logged. Local proxy footage and relevant project text are sent to Gemini when
running draft, index, select, or review. There is no automatic fallback to a different model.

## Run one chapter

Run from `media-search/scripts/`. The commands below demonstrate the Cold Open of the
existing Wick project. Change the chapter and output folder to run another pilot.

```powershell
$project = 'D:\SpearFia\projects\cwi-003-john-wick-gta6-six-stars'
$work = 'D:\SpearFia\pilots\my-media-edit-pilot'
$model = 'gemini-3.5-flash'
python pilot.py prepare --project $project --chapter 'Cold Open' --work $work --limit 12
python edit_pilot.py draft --work $work --model $model --max-calls 1
python pilot.py index --work $work --model $model --limit 12 --max-calls 12
python pilot.py select --work $work --model $model --limit 4 --max-calls 12
python edit_pilot.py render --work $work --variant baseline
python edit_pilot.py render --work $work --variant selected
python edit_pilot.py render --work $work --variant planned
python edit_pilot.py review --work $work --model $model --start 0 --seconds 90 --max-calls 1
python edit_pilot.py render --work $work --variant revised
python edit_pilot.py showcase --work $work
python pilot.py report --work $work
```

Model availability is account-dependent. The default is Gemini 3.8 Flash, which the API
recommended when 2.5 Flash was rejected. The first live pilot used 3.5 Flash after 3.8
returned overload errors. This is availability handling, not a claim of model superiority.

Every attempt consumes a per-command call reservation, including failed attempts. Index and
selection record HTTP 503 windows and continue to independent candidates within the budget;
other failures stop the command. Resume explicitly with a bounded budget. Successful answers
are cached; failed requests are recorded. The limit is calls, not a dollar cap. Inspect
`usage.jsonl` for actual input/output/cached/thinking token fields returned by the service.
`select --max-calls 0` uses cached verification only and records remaining candidates as
retryable. A daily quota error is a stop condition; do not rotate models to bypass it.

## What the pilot does

1. **Prepare:** snapshots the selected chapter and fingerprints narration, visuals, links,
   voice audio/alignment, and the timeline plan. The chapter must have linked VO and an
   existing assembly plan. ASR boundary inference is explicitly marked in the snapshot.
2. **Draft:** generates the full chapter's Editing Script once, including visual purpose,
   mandatory predicates, and one restrained treatment per cue. The narration is immutable.
   Existing exact directions and generated evidence-label text are preserved.
3. **Index:** discovers cuts locally, subdivides long takes into overlapping windows,
   produces silent low-resolution proxies, and describes them with sparse video sampling.
   Source hashes, local intervals, provenance, and sampling status stay attached.
4. **Select:** filters by subject pool and ranks descriptions against narration and visual
   purpose. It verifies up to three shortlisted windows per LIVE cue at denser sampling.
   Each required predicate needs yes/no/uncertain plus an observation. Every yes must have
   an evidence timestamp inside the selected trim. Unknown exact identity stays unresolved.
5. **Render:** creates baseline, selected, planned, and revised comparison videos with the
   same VO. One verified interval replaces the start of its cue; remaining footage retains
   the baseline. Clips are never looped to claim complete coverage. Gaps are dark placeholders.
6. **Review:** Gemini sees the plain selected assembly with audio and the original plan.
   It proposes timestamped changes by stable cue ID. No-change is allowed. Bad footage is
   an issue, not permission to weaken the match requirement. Locked edits cannot change.
7. **Report:** lists unresolved matches and actual model usage. Creator preference and
   audience-retention improvements are not inferred from model scores.

## Editing Script and presets

`editing.md` is the authoring source. Its single `pilot-edit` metadata record is authoritative;
the table is a readable view, not a second input. `editing.initial.md` is an immutable
comparison snapshot; revisions are archived in `history/`. This experimental format is
not a new public Spear Fia schema and must not be pasted into production `edit/edit.md`.
The production parser currently treats all bullet lines as executable commands.

Available presets: none, punch (100 to 112 percent), drift (100 to 105 percent), title
(rise/fade), stamp (five-step size settle), and callout (dim plus target rectangle). Preset parameters
are bounded and timing is chapter-relative. The prototype renderer is ffmpeg; it does not
claim these presets have been implemented or verified in FilmCraft or Resolve. No music,
sound-effect generation, automatic ducking, or caption-animation pass runs in this pilot.

Each review request is at most 120 seconds. For longer chapters, run overlapping windows;
the reviewer maps window-local observation times into chapter time. A script, alignment,
or baseline-plan change requires a new work directory. Changed source media invalidates
selection. Changed trims require re-verification. A final viewing is still required.

## Efficiency and evaluation

Observation responses are reused through a content-addressed `pilot-cache/` beside work
folders. Cue matching has a separate revision key; a changed cue cannot reuse an old fit
decision. Prompt/model/sampling changes produce new response keys. This is persistent
application caching, not paid provider context caching. No provider caches are created:
the pilot's small request volume does not yet justify their storage overhead.
Requests are spaced at least 13 seconds apart within a sequential run to accommodate the
observed five-request-per-minute free-tier limit. Run model commands sequentially; this
pilot does not provide a multi-process rate limiter or a shared-write lock.

Start with lexical matching, which adds no model calls or dependencies. Add embeddings
only if the pilot demonstrates paraphrase misses. Sparse indexing cannot prove an event
is absent, and source metadata cannot establish that an action is visible. Model verification
is still subject to error; it is kept distinct from creator acceptance.

Compare baseline vs selected for footage relevance, selected vs planned for the initial
edit treatment, and planned vs revised for Gemini's changes. `review.html` (from report)
provides local playback and exports creator judgments. Import the exported JSON with
`python pilot.py evaluate --work $work --evaluation <downloaded-file>`.
Measure relevance, clarity, repetition, exact-match false acceptance, creator acceptance,
and actual token usage. A visually quieter but relevant clip can win. Cost per accepted clip
is undefined until human acceptance and actual billed cost are supplied.

## Checks

```powershell
python -m unittest test_pilot -v
```

On a Windows sandbox whose default temporary directory is not writable, set TEMP and TMP
to an existing writable test folder for that command. Tests cover mandatory predicates,
exact-match uncertainty, final-trim evidence, timestamp conversion, edit locks, cache reuse,
call budgets, narration-aware ranking, and literal text handling.
