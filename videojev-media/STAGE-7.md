<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# Stage 7: workflow write-up

Stage 7 documentation is complete. The creator requested this write-up after
Stage 6; that request does not change its recorded **gate incomplete** result.
No deployment or merge is performed by this stage.

The entrypoint is [SKILL.md](SKILL.md), with operation details in
[SCRIPT-FIRST.md](SCRIPT-FIRST.md). This describes the approved script-first
path and existing commands; the separate short editing experiments are not
part of this production workflow.

## Delivered result

Project: `D:\SpearFia\projects\cwi-003-jev-demo`.

Final review: `sync/review-plan-1793469563-layers-graphics-final.fcproj`.
The creator's edited proxy review, earlier references and every saved search
result remain available. The original cwi-003 project was preserved.

| Check | Result |
| --- | --- |
| Saved edit selected for finalization | 986 footage placements, 356 masters, 44 sources |
| Completed master processing | 356; zero failed masters and zero unmapped selected items |
| Source resolution | 248 masters from 1920x1080 sources; 93 from 720-line sources; 15 from 640x480 |
| Hidden/unused master fetches | None in the selected-master plan |
| Native timing, source-in, speeds, zooms, audio and graphics | Preserved; coordinate round-trip tolerance is `1e-9` pixels |
| Render checks | Normal, slowed and animated-zoom samples all passed approximate frame checks |
| Captions | 2,045 converted with `graphics.upgradeCaption`; text/timing verified, original captions removed |
| Selected quality conflict | Clip 1213 at **40:17.733-40:20.633**, source `pksOSHCKp2k` at 180.3125-183.2125 s |

The quality conflict was flagged while preserving the creator's selection.
The all-1080p gate remains unmet. Downloaded dimensions do not prove that higher
formats are unavailable; no new format investigation was performed in Stage 7.

| Below-1080p source | Masters | Downloaded dimensions |
| --- | ---: | --- |
| `btE4KpPW7lo` | 22 | 1280x720 |
| `-AdrCxkpdDc` | 3 | 1280x720 |
| `w183dAjwewI` | 2 | 1280x720 |
| `xgAjogam-Gs` | 21 | 1280x720 |
| `N2qFlMcN4jQ` | 2 | 1280x720 |
| `CFGq-W9YJqY` | 15 | 640x480 |
| `gDHSCT7mjkI` | 10 | 1280x720 |
| `P6XXIMUngM8` | 4 | 1276x720 |
| `7pT_09yr6-8` | 18 | 1280x720 |
| `FAYZ2XDBtRg` | 8 | 1276x720 |
| `S9xvhAvlxC0` | 2 | 1280x720 |
| `kIAyoGJDnCI` | 1 | 1280x720 |

## Search, quality and timing

The approved draft covers 670 sentences: 300 specific and 370 general, with
97 group/query pairs. General pools use local quality scans without object
queries. Specific search reused 222 cached pairs and processed 239 new pairs
across 41 sources in **48.33 minutes**, peaking at **13,133 MiB allocated VRAM**.
Grounding and confirmation took 31.42 minutes; vision encoding took 4.09 minutes.
The 41-source general scan took 10.32 minutes; script-first Stage 4 took 5.38.
These stages have different workloads and must not be combined into a claimed
controlled speedup. Stage 6's resumed elapsed counter spans interruptions and
is not a clean end-to-end active-work measurement.

Independent fine sampling found 14 coarse-dropped examples among 18 confirmed
audit samples from two long sources. This uses the same model and sampled,
potentially overlapping spans; it is not a human-verified recall percentage.
The known Movieclips template excluded eight tails across 22 sources with zero
matches in 880 sampled interior control frames. That supports one layout;
other outros and failed alternatives remain a quality limitation. The earlier
10/10 synthetic logo control does not measure real-world outro detection.

The original automatic review placed 976/1,077 slots with 266.5 seconds empty;
those are pre-edit figures, not remaining gaps in the creator's final edit.
Its source-range repeat checks passed. Creator editing can introduce repeats;
the chosen edit was preserved. No numeric
creator-rated match accuracy was collected, so the plan's 80% target is unverified.
The age-gated `tJbzMqJGH4k` was not bypassed. The six-slot HUD remains manual.

Stage 5's cached fill retry was accepted for progression. Its new-query
helicopter test remains unfilled: matches existed but usable unused footage
with the required clean handles did not cover the requested gap. Existing
`fill`/`swap` provenance is validated for proxy reviews, not relinked HQ inputs.

## Evidence and handoff

Under the demo project, retain:

- `production/jev-script-stage4-report.md`: original assignment and shortage report.
- `production/jev-stage5/comparison.html`: rejected attempts and accepted retry.
- `media/jev/script-first/stage5/creator-progression.json`: explicit Stage 6 authorization.
- `media/jev/script-first/stage6/5289ebdcd1747b61/verification.json`: native and frame checks, low-resolution files and quality flag.
- `media/jev/script-first/stage6/caption-upgrade-be68069353abc943.json`: caption API receipt.
- `production/jev-improvement-analysis.md`: measured timing/token analysis; its Stage 6 status is historical.

The coordinate fix passed 31 tests, including actual ffmpeg alignment, native
round-trip regression cases and rejection of changed timing/text. Stage 7 adds
documentation only; skill metadata, local references, CLI examples and Markdown
are validated without rerunning inference, downloads or the media pipeline.

Priority follow-ups remain broader quality rejection for chosen clips and
alternates, accidental tiny-cut prevention, and a controlled same-window query
batching test. Full feature persistence is unjustified by the measured reuse.
These are proposals, not changes included in this write-up. Final human picture
and sound acceptance and any resolution exceptions remain the creator's decision.
