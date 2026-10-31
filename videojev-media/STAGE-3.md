# Stage 3: indexing and review gate

Status: **stopped cleanly at the creator's request before the performance revision**.
Assignment has not started. The checkpoint preserves 21 completed videos,
466 saved candidates and 638 model results. Raw requests/results, sampled clips,
QC files and SQLite scores remain intact; the checkpoint is recorded under the
demo's `media/jev/checkpoints/stage3-v1-stopped/`.

The creator's pasted checklist is preserved byte for byte in the demo project.
The approved source project was copied without its old `B-roll` folder; 749 old
B-roll links were removed from the copy, retaining 10 VO links and 4 music links.
Script approval still passes in the demo. The original project is read-only.

## Inputs and downloads

The checklist contains 48 distinct video IDs. 47 proxies downloaded; one source
is age-restricted and was skipped without cookies or an age-gate bypass:

- [tJbzMqJGH4k](https://www.youtube.com/watch?v=tJbzMqJGH4k): YouTube requires
  sign-in to confirm age.

Eleven downloaded sources are below 480p, within the permitted 360–480p range.
Every available proxy was measured with `qc.crop`; its crop is preserved for
sampling and review. Full titles, dimensions, durations, crops, errors and
per-video download times are in the download report.

## Outputs

- [Coverage report](D:/SpearFia/projects/cwi-003-jev-demo/media/jev/coverage.md).
- [Contact sheets and review](D:/SpearFia/projects/cwi-003-jev-demo/production/jev-review/review.html).
- [Download report](D:/SpearFia/projects/cwi-003-jev-demo/media/jev/download-report.json).
- [Current progress](D:/SpearFia/projects/cwi-003-jev-demo/media/jev/index-status.json).

The project's `media/jev/` directory also retains `candidates.json`,
`score-windows.json`, `timing-report.json`, `representatives.json`,
`miss-audit-plan.json`, `miss-audit-report.json` and `black-filter-report.json`.
Windows proxy/cut caches are on C:; the shared score table is
`D:\SpearFia\library\jev\index.sqlite`. Model features remain in RAM only.

## Execution and resuming

The Windows orchestrator sends atomic request/result JSON files to one resident
Ubuntu worker using the authors' pinned FlashAttention 2 stack. The existing
Windows baseline supplies Pillow for rendering; no package environment was changed.
The process was launched with `Start-Process -WindowStyle Hidden`, with stdout
and stderr redirected to `C:\SpearFia\cache\cwi-003-jev-demo\stage3-logs`.

```powershell
py -3.11 C:\dev\spearfia\skills-videojev\videojev-media\jev.py --project D:\SpearFia\projects\cwi-003-jev-demo status
```

After a stopped/failed run, `jev.py ... index` reuses downloaded proxies, sampled
cuts, completed model requests and candidate QC. Adding a URL to another group
updates its question list without downloading the video again. No `assign` or
timeline command is called by indexing.
Changing the questions on an existing video recomputes affected window groups;
unchanged groups reuse their completed results. No disk feature store is used.

## Search and gate checks

- All three rounds use context **32,768**: 0.2 fps, 0.5 fps, then 2 fps, with
  thresholds 0.20, 0.30 and 0.50. Short videos skip the coarse rounds as planned.
  Padded overlapping windows carry the union of their questions and are split
  to bounded files before preprocessing. Query variants use the maximum per cell.
- Complete prompts are measured before encoding. Only the image preprocessing
  budget is lowered if needed; language context, requested fps and questions stay
  fixed. A changed fps, missing audit modules or insufficient VRAM stops the worker.
- Source black spans are measured on the cropped picture. Cells with a black
  sampled frame do not supply evidence. Candidate spans split at black intervals,
  then receive `qc.measure`/`pool.flags_of` checks. Frozen/black candidates fail.
  Genuine dark images are retained under the strict source/thumbnail detectors;
  raw QC measurements and rejected flags remain available for review.
- Candidate runs must last at least 1.5 s and are split into pieces no longer
  than 12 s. Each piece gets shuffled target/distractors/"None of these."
  Confirmation passes only when the target is top-ranked with probability ≥0.60.
  Failed results remain in the report. Two-second handles stop at black spans.
- Sparse MP4 headers can extend the final packet by a sample period. Stored
  score bounds are clamped to the requested source window; native score midpoints
  and the corrected `round=up` sampled pictures are preserved.
- The independent miss check scans three predetermined 120 s stretches in each
  of the two longest downloaded sources: `7Bp0pgoex3o` (34:49.963) and
  `BI4mzl9zAQ8` (32:58.433). Its plan was saved before coarse processing.
  Comparison uses actual retained coarse windows, including padding and merged
  question lists. Reports retain fine/coarse probabilities, full choices and
  missed seconds. This is sampled recall using the same model, not an exhaustive
  measurement or shot-boundary annotation.
- Representative sheets show up to three fixed-seed random cells above each
  threshold and the three nearest cells below it. Missing samples are labeled;
  black/unavailable thumbnails are omitted. Hard needs get complete multiple-choice
  distributions beside every representative example, including failed choices.
- All 21 exact requirements stay strict and explicitly unfilled pending scene
  review. `gta6-six-slot-hud` remains manual. Explicit film-title conflicts are
  excluded from usable supply; compilations and uncertain source scope are flagged.

Validation: 20 checks pass across the standard and existing Pillow environments, covering URL preservation/group expansion,
protected project copying, cache updates for new question mappings, black/gap
decoding, padded-window merging, source conflicts and sparse-tail timestamp bounds.
The full report renderer was exercised and an actual control sheet inspected.
Renderer tests also prevent false misses from merged question windows and prevent
planned-but-incomplete sources from counting toward the two-source audit gate.

The remaining videos will resume under the creator's revised quota, confirmation
and timing rules. Completed videos will not be recomputed. Final counts, timing,
VRAM and gate outcome will be recorded after that run.

## Unattended revised run

`stage3_resume.py` freezes the 21 completed source IDs in `resume-policy.json`.
It preserves all 638 old model results and verifies their hashes and the frozen
SQLite score cells before declaring the gate ready. New source work uses the
creator's quota, spacing, quality-choice, freeze-only, fine-clip reuse,
round-2 bypass and deferred-variant rules. Mandatory recall and representative
tests remain separate from quota-limited production work.

The process runs with a hidden console through Windows process management,
independently of this agent session. The script itself writes:

- `media/jev/speed-first3.md` and `.json` after three revised initial passes.
- `media/jev/logo-option-report.md` and `.json`, including known synthetic
  corner-watermark controls. This does not establish real-logo accuracy.
- `media/jev/stage3-summary.md` and `.json` when finished or failed.

Read only `stage3-summary.md` first when the creator reports the gate ready.
The agent must not poll, wait on, or inspect logs/images during the unattended run.
Assignment remains out of scope. The revised implementation passes 26 checks.
