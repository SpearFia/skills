# Approved script-first beats

The creator approved the new interpretation: 670 narration sentences, 300
specific and 370 general. The interpretation is frozen in the demo's
`media/jev/script-first/beats.json`, with an approval receipt and script hash.
No old Subject labels, cue boundaries or narration quotas define the new plan.

The ten general pools contain whole source videos from their own group boxes.
They have no visual query or positive-score requirement. Local ffmpeg black
scans and Windows OCR exclude black frames and text cards. Ordinary HUD,
subtitles, conversations and other footage remain eligible. General selection
divides the largest unused stretches and shares one source-range ledger across
groups, preferring sources not used in the previous 60 timeline seconds.

The text-screen filter samples at 2 fps, then runs local OCR only on mostly flat
backgrounds. It ignores ordinary corner HUD and bottom subtitles. Exclusion
boundaries are approximate; designed end cards with complex backgrounds can be
missed. Completed per-video scans are cached. No VideoJev or language model is
used for general-pool filtering. The Windows OCR decoder reads memory so it
cannot leave the next frame's PNG file locked.

The 97 distinct group/query pairs come from specific approved beats. Native
per-question probabilities are reused from the saved worker results, with the
original bounds and provenance. Legacy summaries that take a maximum across
different questions or variants are not reused as a single question. Existing
scene-confirmation decisions and old need duration targets are not inherited.
Untested stretches are recorded without declaring the footage absent.

Initial preparation found 788 reusable native score windows, 222 cached
video/question pairs, 239 uncached pairs and 10 pairs blocked by the age-gated
GTA 6 source. The uncached job manifest is preparation data, not a worker inbox;
it cannot launch inference. Context remains 32,768. The HUD stays manual.

The checklist places blocked sources first. All group URLs and equivalent
optional-query additions are preserved. Unmapped optional entries remain
archived and inactive, including the old grieving-man control. They are not
promoted into general pools. `tJbzMqJGH4k` requires a creator replacement and is
never sent to a downloader or model by this path.

```powershell
py -3.11 videojev-media/jev.py prepare-beats --project D:\SpearFia\projects\cwi-003-jev-demo
py -3.11 videojev-media/jev.py general-pools --project D:\SpearFia\projects\cwi-003-jev-demo
py -3.11 videojev-media/jev.py status --project D:\SpearFia\projects\cwi-003-jev-demo
```

`prepare-beats` records the already granted approval, validates the approved
script hash, compiles questions, reuses saved scores and refreshes the checklist.
It does not download, scan media, run a model or rebuild a timeline.
`general-pools` performs local quality scans and refreshes pool supply when done.
It skips completed scan files. A `media/jev/script-first/stop` file stops the scan
at the next video boundary, preserving every completed result.

New files live under `media/jev/script-first`. The original needs, scores,
completed-video cache, assignments, links, masters and FilmCraft reviews remain
saved. The old cue-based index/assign/build entry points refuse this project
after approval. This prevents silently returning to the earlier gap plan.
Stage 5 remains stopped.

## Specific-query run

After general pools are ready, `jev.py specific-queries --project <demo>` runs
the 239 uncached video/question pairs across 41 downloaded sources. Existing
cached pairs are not resubmitted. Each request contains only approved visual
queries or a mechanically generated choice check of the same description.
General pools never receive a model query.

The resident Ubuntu worker retains context 32,768 and in-memory feature reuse.
All tasks, score vectors, confirmations and timing are saved in a separate
namespace. Per-question cache keys include the physical source window, model
pins, question and options, so changing a batch does not rescore earlier
questions. Identical physical questions from overlapping source groups share
one inference. Confirmation uses the already sampled 2 fps parent when it
covers the piece; coarse parents are not upsampled for confirmation.

The three rounds retain their accepted fps and thresholds. A question retaining
more than half a long source in round 1 skips round 2. The script confirms up to
three highest-scoring, spaced main samples per new video/question pair. It also
performs an independent 2 fps miss audit on two long sources and displays random
above-threshold samples plus near misses. All fine-window scores remain saved;
these confirmation counts do not become narration duration quotas.

The run writes `production/jev-script-first-summary.md` throughout and writes
`media/jev/script-first/query-results/speed-first3.md` after three videos. It
stops at `specific_query_gate_ready` (or a failure/incomplete state), with review
sheets in `production/jev-script-query-review/review.html`. Named scenes still
require creator review. It does not assign clips, rebuild FilmCraft or start
Stage 5. Create `media/jev/script-first/query-results/stop` for a clean stop after
the current model request; completed results are retained for resume.

## Script-first Stage 4

After creator acceptance of the query summary, run `jev.py script-timeline
--project <demo>`. It word-times every approved sentence against the saved
narration, assigns short literal inserts first, then fills the remaining time
from query-free pools in the permitted groups. Adjacent general sentences can
share four-second shots. No old visual-cue boundaries or Subject labels are
used. Missing literal evidence stays empty; the six-slot HUD stays manual.

Saved multiple-choice answers can be reused through an approved main-query
reference when older answer wording differs. A variant cannot borrow another
target's answer. Numeric choice thresholds, saved quality failures and known
source conflicts still apply. Optional specific sources receive cached/local
text and black filtering without joining general pools or rerunning VideoJev.

The allocator reserves all chosen source ranges globally, prefers spacing and
source variety, and rejects coherent 2 fps perceptual copies across URLs.
Perceptual detection is approximate. After allocating the entire top track, it
chooses up to two alternates per clip, avoiding top ranges. Masters are silent
480p files with 2.5-second handles. The existing cutter, project-scoped pusher
and headless FilmCraft builder are reused. Earlier reviews and saved search
results remain intact. Only the demo's footage links are replaced, with backup.

Assignments, masters, native snapshots, timing and checks are under
`media/jev/script-first/stage4`. The job writes its own short summary to
`production/jev-script-first-summary.md` and the full gate report to
`production/jev-script-stage4-report.md`. Status becomes
`script_stage4_gate_ready` after native timing, silence, handles, alternate reveal
and render checks pass. Interactive playback and scene identity remain for
creator review. The job stops before Stage 5. A `stage4/stop` file stops at the
next task boundary, preserving completed artifacts.

## Stage 5 edit commands and comparison

`fill` takes an empty timeline range; `swap` takes a timestamp within a visible
footage clip. Both require `--review`, save a separate `review-stage5-*.fcproj`,
and preserve the input file. They leave narration, music, cards, captions and
other clips unchanged. Examples:

```powershell
py -3.11 videojev-media/jev.py fill --project <demo> --review <review.fcproj> --at 12:03-12:06 --need <question-id>
py -3.11 videojev-media/jev.py swap --project <demo> --review <review.fcproj> --at 12:03 --need wick1
py -3.11 videojev-media/jev.py fill --project <demo> --review <review.fcproj> --at 12:03-12:06 --group wick1 --query "A car moves through traffic."
```

`--need` accepts an approved question/visual ID, an unambiguous approved cache
reference, or a film/game group for a query-free general shot. It reuses stored
choices and scores. `--query` reuses an already known question when possible;
otherwise it sends only the new text and its mechanical multiple-choice check
to the pinned Ubuntu worker at context 32,768. It scans at 2 fps, starts with
promising saved windows, and stops when it has one confirmed unused shot of the
requested duration. Completed Stage 3 scores are never rewritten. New query
answers live in a separate per-query cache and can be reused by another edit.
General footage still uses only its own group URLs and local text/black scans.

The source ledger is read from visible native clips, including the creator's
trims and selected alternates. A new shot must cover the entire requested slot,
avoid existing visible footage and pass the same perceptual repeat filter.
Already existing repeats in a creator edit are reported, not silently repaired.
Speed/reverse edits require explicit source-time mapping before these commands
can operate. An unfilled result preserves the gap instead of shortening the
request or substituting unrelated footage.

`stage5-test --project <demo> --review <edited-review.fcproj>` first saves a
byte-identical creator reference. It reconstructs the complete pre-edit layered
review from the unchanged base, saved assignment and masters, then checks it
against the saved native track snapshot. This uses no inference or new
assignment. Tests use disposable copies and representative real gaps, preferring
the original review and then the creator reference when saved evidence is
available there. The new-query test mechanically prefixes an approved literal
description with `Visible scene:` to exercise an uncached query without changing
the approved interpretation. It also tests one cached replacement.

The comparison page renders the same intervals from the automatic original,
creator reference and Stage 5 outputs. It is saved to
`production/jev-stage5/comparison.html`; the short summary is
`production/jev-stage5-summary.md`. Status becomes `stage5_gate_ready` only if
the cached fill, new-query fill and cached swap succeed. A missing match produces
`stage5_gate_incomplete`. The workflow stops before Stage 6. A
`media/jev/script-first/stage5/stop` file stops at the next task boundary.
