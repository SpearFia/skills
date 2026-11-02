---
name: videojev-media
description: Search creator-supplied YouTube footage with VideoJev, assemble an approved script-first FilmCraft proxy review, and finalize the creator's selected clips. Use for this staged Spear Fia footage workflow, including cached fills, swaps and higher-resolution relinking.
license: MIT OR Apache-2.0
---

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# VideoJev media

Use the deterministic pipeline in this folder. Resolve an explicit project and
saved review before changing files. The validated project is
`D:\SpearFia\projects\cwi-003-jev-demo`; the original
`cwi-003-john-wick-gta6-six-stars` stays read-only. This is a staged prototype;
new projects need their own approved draft and source mappings.

Read [SCRIPT-FIRST.md](SCRIPT-FIRST.md) for the operation being requested.
Read [STAGE-7.md](STAGE-7.md) for measured results and unresolved demo gates.
For environment repair only, use [STAGE-0B.md](STAGE-0B.md) and the pinned
[Linux requirements](requirements-wsl.lock.txt). Preserve the Windows baseline.

## Planning and source scope

Make one sentence-by-sentence pass over the approved narration. Classify a beat
as specific only when it literally names something visible; give it a short
visual description. Otherwise use that film/game's general pool without a
positive visual query. Do not inherit old Subject labels or cue boundaries.
Show the draft before inference; helpers can write approval receipts, so call
`prepare-beats` only after the creator explicitly accepts that exact draft.

After approval, use scripts and VideoJev grounding/choice checks. Do not make
another semantic planning pass or have the assistant judge sampled frames.
Use group URL boxes for John Wick 1-4, GTA 3-6, San Andreas and Vice City;
optional query boxes remain scoped additions. General pools use their own
group URLs. Keep manual requirements and unavailable literal shots explicit.
Short actions get short inserts; remaining narration uses the permitted pool.
General footage does not establish that a missing literal action was found.

## Run the approved path

From the checkout root, use `py -3.11 videojev-media/jev.py COMMAND --project PATH`.
Stop at the requested gate; a saved file alone does not establish visual acceptance.

| Command | Purpose |
| --- | --- |
| `prepare-beats` | Compile the approved draft, source mappings and reusable scores |
| `general-pools` | Run cached local black/text-screen filtering without object queries |
| `specific-queries` | Search only missing approved video/question pairs; write review sheets |
| `script-timeline` | Assign the whole narration, cut proxies and build a separate layered review |
| `fill` / `swap` | Edit a proxy review from saved evidence or an explicitly requested new query |
| `finalize` | Upgrade selected visible masters from the creator's saved review |

Use `--review` for editing/finalization and the arguments documented in
SCRIPT-FIRST.md. The legacy `index`, `assign` and `build` route is disabled for
script-first projects. Experimental editing-study/recipe commands are separate;
they do not authorize production deployment or changes to this selected edit.

Keep [config.json](config.json) pins, context **32,768**, rounds **0.2 / 0.5 / 2 fps**,
and thresholds **0.20 / 0.30 / 0.50**. Confirmation requires the matching option
to win with probability at least **0.60**. Use plain visual descriptions.
Keep vision features in RAM; a disk feature cache has not been justified.
The Ubuntu worker uses FlashAttention 2 and causal-conv1d; Windows orchestrates
the job files and FilmCraft. Reuse completed native scores and per-question
provenance; do not resubmit finished videos or blend different variants' scores.

Exclude black/text screens and known rejected source ranges, preserving source
timestamps. Apply quality eligibility to both chosen shots and alternates.
The known Movieclips endcard template covers one layout/channel, not all outros.
Use sampled 2 fps miss checks on at least two long sources independently of
coarse retention. Review sheets include random above-threshold samples, near
misses and full multiple-choice distributions for hard needs.
List blocked URLs at the top of the checklist, without cookies, sign-in or
bypass attempts.

## Editing and finalization

Allocate chosen footage globally without source-range repeats, then offer up to
two alternates. Keep **2.5 s handles**, clamping only at physical source ends.
Preserve the creator's selected edit and report existing repeats or exclusion
conflicts. Use proxy reviews for `fill`/`swap`: their provenance ledger is not
validated for relinked HQ inputs. Constant forward retiming is supported;
reverse, frame holds and animated time remapping require explicit mapping.

Finalize only masters referenced by visible selected footage. Reuse downloaded
parts and validated master receipts; keep proxies and previous reviews.
Use FilmCraft's API for relinking, scale source anchors with resolution, and
verify native timing, source-in, speed, zooms, graphics and audio. Only pixel
coordinate round-off up to `1e-9` is tolerated; timing remains exact. Report
actual source dimensions and failed requests. Lower-resolution footage must
not be presented as genuine 1080p. Save a separate `-final.fcproj`.

Caption conversion is a separate requested operation, not a `finalize` option.
Discover FilmCraft's `graphics.upgradeCaption`, pass explicit caption IDs on a
working copy, and save with `file.saveAs`. Verify text/timing, removal of the
original captions to avoid double display, and unchanged existing clips.
Finalize that converted working copy; retain the creator's earlier review.

## Background work and reporting

Use a hidden independent process with redirected logs and script-written status.
Keep caches on C: and project deliverables on D:. Respect the creator's request
not to poll, wait, or read logs/images during the run. When asked for status,
read only the relevant short summary first, then necessary failure metadata.

Resume the same approved inputs and cache namespace. Preserve every saved
result. A stop marker is cooperative: in-flight cuts can finish before exit;
confirm exit before calling the job paused. Remove only the stop marker when
resuming. Never overwrite a creator edit to repair a failed run.

Summaries live in `production/jev-script-first-summary.md`,
`production/jev-stage5-summary.md` and `production/jev-stage6-summary.md`.
Detailed state and receipts are under `media/jev/script-first/`; the first-three
speed report is written by the query script itself. Distinguish technical
completion, visual acceptance, sampled recall and unresolved shortages.
Stop after the requested gate. Merging or installing this prototype requires
a separate creator request.
