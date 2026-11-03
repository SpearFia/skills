<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Proxy editing trial

The creator subsequently authorized [isolated Star 4 contextual auditions](EDITING-AUDITION.md)
from the frozen v3 snapshot. That separate, creator-selected preview path leaves
the deployment and HQ restrictions below intact.

Current creator policy: **deployment and HQ finalization are disabled**, even if
the historical calibration gate would pass. Overlay entrances use pop; the
motion-scene families are allowed (2026-11-03). Continue with
[recommendation-only studies](EDITING-STUDY.md) on complete videos of any length.
John Wick and GTA History are excluded. The Star 4 artifacts below are archived and must not be rerun or
rewritten. Importing their completed creator labels is read-only analysis.

The editing recipe contract lives in `spearfia-spec`, branch `exp/editing-recipe`.
This workflow reads the creator's saved native edit, not its old assignment.
It preserves the original projects, frozen beats, approvals, earlier reviews
and the stopped Stage 6 job. Generated media and review artifacts stay outside Git.

`jev.py edit-prepare` and `edit-preview` reject excluded projects and empty native
timelines before inference. Preparation requires an existing
approval receipt; it cannot create one. Use the short-study workflow for the next
diagnostic trial.

Preparation runs no inference. It snapshots the exact native edit, canvas and
timebase; maps visible sources, trims, crops and constant speeds; reuses approved
beat timing and narration hashes; and records local visual intent and observations.
Only exact source/question observations covering the selected interval are attached.
Scene and source review status remain explicit. Reverse playback, frame holds,
time remapping, excluded sources and manual-overlay conflicts remain review flags.

Supplied labels generate pop variants of the existing three treatment families.
The historical style gallery retains all four motions. An automatic reveal needs
an unambiguous instruction such as
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
collects creator choices separately from model predictions. Each option has a
readable name, a description and a five-second video using the actual treatment
and motion renderer. Use its preview button or compare all twelve combinations
in `style-examples/index.html`. The clips are silent style references with sample
words; labels still concern the actual beat and its evidence. Reference clips
are cached, generated outside Git, and require no model calls.

The first ten examples
are calibration examples, the rest held out. Save its downloaded labels as
`calibration-labels.json` beside the recipe. Criteria are fingerprinted before live
decisions. At least twenty eligible held-out decisions must achieve 95% agreement
and zero creator-reported unsupported-evidence errors. This historical pilot gate
is not an accuracy guarantee or permission to deploy. The creator has separately
disabled application, independently of its result.

HQ finalization is currently blocked by experiment policy. The retained
implementation would require a separate instruction after picture and sound review.
The matching `approval.json` must contain `recipe_sha256`, `preview_sha256` and
`picture_and_sound_reviewed: true`; never fabricate that review. An approval file
does not override the disabled deployment policy.

This path calls no editorial model. It reuses verified HQ masters, upgrades only
selected dependencies, validates source alignment and native geometry, and renders
inserts again from HQ bindings. Relinking only the background cannot satisfy the
insert dependency check. Captions remain native and inserts contain no captions or
audio. Missing, lower-resolution or unsupported dependencies leave finalization
incomplete. The existing Stage 6 job and stop marker are not resumed or removed.

## TEXT and ACTION grammar

Each `TEXT: <literal>` line is classified separately. Only the exact prefixes
`REPORTED:`, `SOURCE:` and `CHAPTER <n>:` identify source/context lines;
`STAR 4: COSTLY SURVIVAL` remains body text. Under `## Editing` in the video's
`channel.md`, supply `Qualifiers: OUR GUESS / ESTIMATE` (example vocabulary).
Qualifiers match whole lines exactly; no list means no recognized qualifiers.
Several remaining body lines add `unclassified-text-line` for creator review.

Body lines retain their original strings and split only on ` / `. Progressive
candidates need at least two units. Comparison candidates need exactly two units
and a `GRAPHIC:` line containing comparison, versus or paired. A slash alone
cannot establish comparison intent. Source cards retain the unsplit body plus
an explicit source or context heading. A qualifier used as a context-card heading
is carried as `source_label`; otherwise it stays `qualifier`. Neither enters the
body labels. The hand-mapped audition MOMENTS are the golden examples.

Use `ACTION: Reveal "<exact unit>" at "<exact spoken words>"; reveal ...`.
Reveal keywords are case insensitive and whitespace may wrap across lines.
Resolve unique aligned quotes against measured words; source cards use the
first unit's anchor. Missing anchors retain `missing-explicit-reveal-anchors`
and omit `reveal_frames`, which the current schema permits. No interval-start
times are invented. Existing readability and evidence checks still apply.

## Star 4 measurement, 2026-11-01

The saved section contains 111 approved beats, 156 selected footage placements and
14,891 frames at 30 fps. Its 960×540 preview retains the native 3840×2160 canvas.
Thirteen candidate windows received live recommendations; none was eligible to
apply. The completed creator review selected 94 keep, eight review, seven source
card pop and two comparison pop choices. Only thirteen rows received model calls:
all chose keep, agreeing with the creator in four; the other nine requested a
graphic. The remaining 98 rows were planner fallbacks, excluded from model
agreement. Candidate availability was deterministic and cannot measure the model's
ability to detect visual opportunities. This reviewed set is development feedback.
The unchanged second preview made zero model calls and reused the render.

An after-the-fact grouped re-read of the saved probabilities on these 13
neighboring beats gives exact agreement 4/13. Each question had 14 options;
the sum of treatment variants exceeds keep in 9/13, and grouped agreement
(graphic versus no graphic, with none-of-these separate) is 9/13. Always
answering "graphic" also scores 9/13. This does not show model skill. Grouping
is measurement only: raw choice, thresholds, eligibility, frozen criteria,
context hashes and disabled deployment are unchanged. No model was rerun.


On the RTX 5070 Ti, cold start was approximately 15.5 seconds. The complete
7,077–9,621-token contexts took 2.37–4.03 seconds, median 2.80 seconds; maximum
allocated VRAM was approximately 10,141 MiB. These are pilot measurements, not a
subsecond performance claim. The 4/13 descriptive agreement above is specific to
this reviewed set, not a general accuracy estimate.

Normal, retimed and animated-zoom source replacements passed representative
alignment and native geometry checks using already-downloaded HQ masters.
Paired technical inserts contained exactly ninety frames at proxy/HQ resolution;
the HQ render used HQ bindings. These technical auditions were not applied to the
review timeline and do not establish editorial quality. The full approved HQ
finalization and creator listening review have not been run.
