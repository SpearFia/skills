<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Proxy editing trial

The editing recipe contract lives in `spearfia-spec`, branch `exp/editing-recipe`.
This workflow reads the creator's saved native edit, not its old assignment.
It preserves the original projects, frozen beats, approvals, earlier reviews
and the stopped Stage 6 job. Generated media and review artifacts stay outside Git.

```powershell
python videojev-media/jev.py edit-prepare --project D:/SpearFia/projects/cwi-003-jev-demo --review D:/SpearFia/projects/cwi-003-jev-demo/sync/review-plan-1793469563-layers.fcproj --out D:/SpearFia/pilots/new-edit-review --section "Star 4"
python videojev-media/jev.py edit-preview --project D:/SpearFia/projects/cwi-003-jev-demo --editing-recipe D:/SpearFia/pilots/new-edit-review/editing-recipe.json
```

Preparation runs no inference. It snapshots the exact native edit, canvas and
timebase; maps visible sources, trims, crops and constant speeds; reuses approved
beat timing and narration hashes; and records local visual intent and observations.
Only exact source/question observations covering the selected interval are attached.
Scene and source review status remain explicit. Reverse playback, frame holds,
time remapping, excluded sources and manual-overlay conflicts remain review flags.

Supplied labels generate variants of the existing three treatment families and
four motion presets. An automatic reveal needs an unambiguous instruction such as
`ACTION: Reveal "Fight won" at "He wins the fight"`, with a unique approved-word
anchor verified against the narration observations. No wording is generated.
Unresolved anchors retain the current presentation. Existing native caption styling
and audio remain intact; animated caption-style auditions are still available in
the separate Remotion pilot, not substituted into this saved edit.

Preview batches justified missing video questions before the Clef phase. Incomplete
editorial intent does not trigger speculative video queries. The existing VideoJev
worker retains its pinned model, context 32,768 and exclusions. Workers started by
this invocation have their own task directories and ownership markers. The worker
releases VideoJev before loading NF4/BF16 Clef through `/v1/systemone`.

Successful decisions cache against the complete context and model revision.
Worker failures keep the current edit and remain retryable. Every packet includes
keeping the current presentation and abstaining. The 0.95 probability / 0.20 lead
threshold never repairs missing evidence or invalid inputs.

`review.html` contains the full proxy preview and review flags. `calibration.html`
collects creator choices separately from model predictions. The first ten examples
are calibration examples, the rest held out. Save its downloaded labels as
`calibration-labels.json` beside the recipe. Criteria are fingerprinted before live
decisions. At least twenty eligible held-out decisions must achieve 95% agreement
and zero creator-reported unsupported-evidence errors. Until then, the draft remains
byte-identical to the saved edit. This is a pilot gate, not an accuracy guarantee.

HQ finalization requires a separate instruction after picture and sound review.
The matching `approval.json` must contain `recipe_sha256`, `preview_sha256` and
`picture_and_sound_reviewed: true`; never fabricate that review. Then run:

```powershell
python videojev-media/jev.py finalize --project D:/SpearFia/projects/cwi-003-jev-demo --editing-recipe D:/SpearFia/pilots/new-edit-review/editing-recipe.json
```

This path calls no editorial model. It reuses verified HQ masters, upgrades only
selected dependencies, validates source alignment and native geometry, and renders
inserts again from HQ bindings. Relinking only the background cannot satisfy the
insert dependency check. Captions remain native and inserts contain no captions or
audio. Missing, lower-resolution or unsupported dependencies leave finalization
incomplete. The existing Stage 6 job and stop marker are not resumed or removed.

## Star 4 measurement, 2026-11-01

The saved section contains 111 approved beats, 156 selected footage placements and
14,891 frames at 30 fps. Its 960×540 preview retains the native 3840×2160 canvas.
Thirteen candidate windows received live recommendations; none was eligible to
apply. Creator intent, mapped-card review and calibration remain outstanding.
The unchanged second preview made zero model calls and reused the render.

On the RTX 5070 Ti, cold start was approximately 15.2 seconds. The section's
2,828–5,305-token requests took 0.97–2.13 seconds, median 1.21 seconds; maximum
allocated VRAM was approximately 9,218 MiB. These are pilot measurements, not a
subsecond performance claim. No creator-agreement accuracy has been measured.

Normal, retimed and animated-zoom source replacements passed representative
alignment and native geometry checks using already-downloaded HQ masters.
Paired technical inserts contained exactly ninety frames at proxy/HQ resolution;
the HQ render used HQ bindings. These technical auditions were not applied to the
review timeline and do not establish editorial quality. The full approved HQ
finalization and creator listening review have not been run.
