# Stage 2: needs and URL checklist

Status: **ready for the creator to paste URLs; stopped before Stage 3**.

[Open the editable checklist](D:/SpearFia/projects/cwi-003-jev-demo/production/media-checklist.md).
Paste video URLs under the relevant need headings. Plain URLs, bullets and
Markdown links work. The same URL may appear under several needs; each heading
provides its tag. No URLs were preselected.

## Contents and coverage

- 50 needs: **49 narration needs plus 1 review-only grieving-man control**.
- All **198 LIVE-footage cues** map exactly once; no cue IDs were invented.
- All **21 exact scene requirements** are retained and have no broad fallback.
- The **45 generated cards** remain separate and unchanged.
- Needs are sorted by estimated seconds, longest first. The total is about
  **2,819 seconds / 47 minutes** of footage demand, estimated using the existing
  pool rate of 2.6 narration words/sec. Exact VO timing belongs to later assignment.
- Every need has a plain visual query, multiple-choice target and distractors,
  source scope and optional compatible fallback. Film chapters and historical
  games are kept separate; original continuity and evidence-label requirements
  remain in the cue snapshot.

Tanks are separate needs for GTA 3, Vice City and San Andreas; police helicopter
coverage includes the GTA 5 exact scene and GTA 4's helicopter-pair requirement.
The approved narration does not request a grieving man, so that hard review
control has **zero cues and zero timeline demand**. It must not substitute for
driving, fighting or injury footage. Its distractors include an exhausted man,
and the police-helicopter choices distinguish a civilian helicopter.

## Locations and original-project safety

Only Stage 2 metadata/checklist files were created under the future demo folder:

- `D:\SpearFia\projects\cwi-003-jev-demo\media\jev\needs.json`
- `D:\SpearFia\projects\cwi-003-jev-demo\media\jev\input-cues.json`
- `D:\SpearFia\projects\cwi-003-jev-demo\media\jev\sources.json`
- `D:\SpearFia\projects\cwi-003-jev-demo\production\media-checklist.md`

This is a prepared workspace, not yet the full project copy. Stage 3 must copy
the approved project there while preserving these files and all pasted URLs.
No `project.json`, VO, music, old B-roll or timeline was copied in Stage 2.
The original cwi-003 script, Visual Script and project files received no edits;
source hashes are recorded in the input snapshot. Its CLI status remained
approved for production.

The [frozen needs](examples/cwi-003/needs.json) and
[cue snapshot](examples/cwi-003/input-cues.json) are also recorded in this branch.
[needs-prompt.md](needs-prompt.md) and [needs-draft.json](needs-draft.json) record
the one-time authoring step. No checklist command invokes an LLM.

## Regeneration and parser gate

```powershell
py -3.11 C:\dev\spearfia\skills-videojev\videojev-media\jev.py --project D:\SpearFia\projects\cwi-003-jev-demo needs
```

Regeneration reads pasted URLs from the existing checklist, preserves their
strings/order, deduplicates within a need and writes `sources.json`. URLs reused
under different needs remain in each group. If the checklist is absent, stored
`sources.json` entries can rebuild it. With a checklist present, its URL lines
are the demo's source of truth, so deliberate URL removals are respected.

The parser rejects URLs outside known need headings, non-YouTube links,
playlist/channel-only links and stored URLs under unknown need IDs. Mapping/query/fallback
validation completes before writing; each output is replaced atomically.
The approved original is explicitly protected from checklist writes.

Tests passed for mixed URL formatting, duplicate handling, cross-need reuse,
URL preservation across regeneration, bad mappings leaving the checklist intact,
and original-project protection. Full-data checks verify 198 unique cue mappings,
21 exact visual requirements, valid fallback chains and name-free queries.

## Accepted production settings

- Context **32,768 for every round**, with the same hard cap.
- Plain visual descriptions rather than names in model queries.
- Black-frame filtering required; retain genuine dark footage and original
  source timestamps. Detection, candidate trimming and review-sheet behavior
  are Stage 3 work, with settings and excluded counts reported there.
- Disk feature persistence remains off.

These decisions are recorded in config/the creator's external build plan. The
historical Stage 0/1 experiment outputs remain unchanged.

## Expanded Stage 3 gate

The external plan now requires all three additions:

1. **Miss check on at least two long sources:** independently chosen sample
   stretches scanned at 2 fps regardless of coarse results; confirm matches with
   multiple choice and report any shots outside coarse retained windows, including
   padding. Include counts, seconds, denominator, source times and score evidence.
2. **Representative sheets:** reproducible random examples above the thresholds
   plus nearest misses below them, rather than only the top three. Exclude black
   images and label insufficient samples.
3. **Hard needs:** tanks, police helicopter and grieving man, with complete
   multiple-choice options/probabilities, chosen answer, correct target and
   pass/fail beside each displayed example, including failures or missing results.

No Stage 3 download, indexing, black-frame filtering, miss audit or confirmation
was run. Those checks wait for the creator's URLs. New files are dual licensed
MIT OR Apache-2.0.
