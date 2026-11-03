<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Short editing studies

Creator policy, 2026-11-03: overlay entrances use **pop**, the motion-scene families
in spearfia `docs/motion-scene-cues.md` are allowed, experiments run on complete
videos of any length, and deployment stays disabled. Do not apply this system to
the current John Wick project or GTA History. Calibration and high
confidence cannot unlock application or HQ finalization. No source project,
approvals, beat plans or previous reviews should be rewritten.

The completed Star 4 review exposed two different problems: recognizing a useful
graphic role and selecting a supplied treatment. Candidate availability in that
trial came from the Visual Script and deterministic timing checks. It was not a
model prediction. Of the thirteen actual Clef judgments, all chose keep; the
creator chose keep in four and a pop treatment in nine. The remaining 98 rows
were planner fallbacks and cannot establish model agreement or opportunity recall.
The review is development feedback, not an untouched held-out quality estimate.

## Import existing feedback

This read-only analysis copies the exact creator export beside the historical
review and adds `creator-feedback.json` and `creator-feedback.html`. It refuses a
conflicting earlier export, verifies frozen criteria and contexts, and invokes
neither model nor timeline worker.

```powershell
python videojev-media/editing_feedback.py --review D:/SpearFia/pilots/star4-proxy-edit-20261101-v3 --labels C:/Users/caesa/Downloads/calibration-labels.json
```

## Prepare a new short study

Use the `editing-study` schema and example in the sibling `spearfia-spec-editing`
checkout. The example teaches the format; its media hash and narration are
placeholders. Supply an actual complete short video, its SHA-256 and duration,
beat narration, a description of the current presentation, and existing labels,
reveal anchors and source lines. Do not invent missing wording or provenance.
Place both media and the manifest outside Git. Keep output outside the source
project. Known John Wick and GTA History project paths are rejected; the full
media duration is probed so a section range cannot disguise a longer video.

Choose a whole-video `calibration` or `held-out` split. Freeze criteria before
testing on separate short videos. A single reviewed video's neighboring beats
must not be presented as independent held-out videos.

```powershell
python videojev-media/editing_study.py --input D:/SpearFia/studies/short/input.json --out D:/SpearFia/pilots/short-study-01
python videojev-media/calibration_examples.py D:/SpearFia/pilots/short-study-01
```

The validator uses Node/Ajv from the sibling `spearfia-spec` installation and
schemas from `spearfia-spec-editing`, matching the current experiment worktrees.
FFprobe and the existing Ubuntu Clef environment are required. The style-example
command uses the existing Remotion renderer and generates just three silent,
five-second pop references. Regenerate the form after generating references by
rerunning the unchanged study command; judgments and references are cached.

Every beat gets a graphic-role question, even when its candidate list is empty.
The opportunity packet omits the menu, candidate count and treatment answer.
Treatment questions include complete pop candidates, keep and none-of-these.
They run independently when candidates exist. An empty menu is recorded as
not asked. No missing menu is converted into a model prediction of keep.

The model judges supplied text and saved observations, not raw video. New video
queries, writing, rendered treatment application and native timeline changes are
outside this diagnostic path. It creates no editing recipe or approval record.
The full media hash, narration, presentation, observations, neighboring narration,
criteria, choices and pinned model revision bind each applicable cache entry.
Changing only a treatment leaves the independent opportunity context unchanged.
Oversized contexts fail at the typed service rather than being truncated.

## Review and compare

Open `calibration.html`, watch each beat, and answer graphic usefulness separately
from treatment fit. The five-second buttons teach the treatment style using sample
words. Model predictions remain in `review.html`, outside the blind label form.
Download `short-study-labels.json`, then use the same input/output with `--labels`:

```powershell
python videojev-media/editing_study.py --input D:/SpearFia/studies/short/input.json --out D:/SpearFia/pilots/short-study-01 --labels C:/Users/caesa/Downloads/short-study-labels.json
```

An unchanged rerun makes zero new model calls and starts no GPU worker. Failed
requests remain explicit and retryable. Failed/unasked questions are excluded
from stage agreement, and stale fingerprints are rejected. Results are descriptive
component measurements; no automatic deployment gate is enabled. A changed frozen
study uses a fresh output folder, preserving earlier labels and results. Validated
creator exports are copied exactly to `creator-labels.json`; later cached runs
reuse them, and conflicting exports cannot overwrite an earlier review.
