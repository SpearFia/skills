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
