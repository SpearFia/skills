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
