# Stage 2: needs and URL checklist

Status: **ready for the creator to paste URLs; stopped before Stage 3**.

[Open the editable checklist](D:/SpearFia/projects/cwi-003-jev-demo/production/media-checklist.md).
Paste video URLs in the ten source-group boxes: John Wick 1, 2, 3, 4; GTA 3, 4,
5, 6; San Andreas; Vice City. Each group URL receives all of that film/game's
automatic questions. Individual need boxes below are optional additions. Plain
URLs, bullets and Markdown links work. No URLs were preselected.

## Contents and coverage

- 50 needs: **49 narration needs plus 1 review-only grieving-man control**.
- All **198 LIVE-footage cues** map exactly once; no cue IDs were invented.
- All **21 exact scene requirements** are retained and have no broad fallback.
- `gta6-six-slot-hud` is **handled by hand**, excluded from group search questions
  and retained as an unfilled exact requirement until manually supplied/verified.
- The **45 generated cards** remain separate and unchanged.
- Optional individual needs are sorted by estimated seconds, longest first. The total is about
  **2,819 seconds / 47 minutes** of footage demand, estimated using the existing
  pool rate of 2.6 narration words/sec. Exact VO timing belongs to later assignment.
- Every need has a plain visual query, multiple-choice target and distractors,
  source scope and source group. Film chapters and historical
  games are kept separate; original continuity and evidence-label requirements
  remain in the cue snapshot.
- **19 specific non-exact needs** fall back to an existing broader need from the
  same film/game. The **9 existing broad roots** end the fallback chains; they
  have no further fallback. No needs or cue mappings were added or removed.
  Existing Chapter 2 armed movement, GTA 6 outdoor setting and San Andreas
  military-vehicle needs supply the broader roots in those groups.
- Queries and confirmation targets describe visible actions. In particular,
  `gta5-cover-escape` asks for running between buildings and turning street
  corners, rather than inferring the person's intention to hide.

Tanks are separate needs for GTA 3, Vice City and San Andreas; police helicopter
coverage includes the GTA 5 exact scene and GTA 4's helicopter-pair requirement.
The approved narration does not request a grieving man, so that hard review
control has **zero cues and zero timeline demand**. Its separate optional box
takes one John Wick 1 URL; group URLs do not enable it. It must not substitute for
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
strings/order, deduplicates within each box and writes `sources.json`. Keys
`group-wick1` through `group-gtavc` retain group-box entries; existing need-ID keys
retain individual entries. `expand_sources(needs, sources)` resolves these into
one deduplicated URL list per question, excluding manual/review-only needs from
group expansion. Group entries are not copied into the individual boxes, so
removing a group URL does not leave stale individual entries. If the checklist is absent, stored
`sources.json` entries can rebuild it. With a checklist present, its URL lines
are the demo's source of truth, so deliberate URL removals are respected.

The parser rejects URLs outside known source-group/need headings, non-YouTube links,
playlist/channel-only links and stored URLs under unknown headings. It rejects
search URLs under the manual HUD and more than one URL for the optional control.
The John Wick 1 content restriction is stated for the creator; URL syntax alone
cannot verify which film a source contains. Mapping/query/fallback
validation completes before writing; each output is replaced atomically.
The approved original is explicitly protected from checklist writes.

Tests passed for mixed URL formatting, duplicate handling, cross-need reuse,
URL preservation across regeneration, bad mappings leaving the checklist intact,
and original-project protection. Group fan-out, manual/control exclusions,
group/individual removal and recovery from stored entries are also tested.
Full-data checks verify 198 unique cue mappings, 21 exact visual requirements,
valid same-source fallback chains and name-free queries.

## Exact coverage while waiting for URLs

All 21 exact requirements are currently unfilled: no sources have been indexed
or confirmed. Each must remain explicit in Stage 3's `coverage.md` until matching
footage is confirmed. A broader fallback cannot fill these rows. The manual HUD
remains unfilled until supplied and verified by hand.

| Exact need | Required scene | Current status |
| --- | --- | --- |
| `wick1-home-fight` | John Wick's home-invasion fight against Viggo's men. | Unfilled; awaiting URLs/search |
| `wick1-nightclub-movement` | John's movement through the Red Circle in John Wick. | Unfilled; awaiting URLs/search |
| `wick1-nightclub-throw` | Kirill throws John out of the upstairs Red Circle exchange in John Wick. | Unfilled; awaiting URLs/search |
| `wick2-driving-warehouse` | John recovers and fights with the Mustang at Abram's warehouse in Chapter 2. | Unfilled; awaiting URLs/search |
| `wick2-wrecked-car` | The damaged Mustang and Aurelio's assessment in Chapter 2. | Unfilled; awaiting URLs/search |
| `wick2-pistol-supply` | The Bowery King supplies the seven-round pistol in Chapter 2. | Unfilled; awaiting URLs/search |
| `wick2-prepared-escape` | John uses prepared equipment in Chapter 2's Rome catacombs. | Unfilled; awaiting URLs/search |
| `wick3-roof-fall` | John survives the interrupted Continental roof fall in Chapter 3. | Unfilled; awaiting URLs/search |
| `wick3-armored-defense` | Chapter 3's Continental defense against armored High Table attackers. | Unfilled; awaiting URLs/search |
| `wick3-armory` | John and Charon rearm in the Continental armory in Chapter 3. | Unfilled; awaiting URLs/search |
| `wick3-exhausted-zero` | The exhausted John faces Zero near the end of Chapter 3. | Unfilled; awaiting URLs/search |
| `wick3-rescued` | The severely injured John is brought to the Bowery King in Chapter 3. | Unfilled; awaiting URLs/search |
| `wick4-driving-traffic` | Chapter 4's Arc de Triomphe driving and gunfight amid traffic. | Unfilled; awaiting URLs/search |
| `wick4-fire-shotgun` | John uses the acquired Dragon's Breath Gen-12 in Chapter 4's apartment fight. | Unfilled; awaiting URLs/search |
| `wick4-stairs-fall` | Chidi sends John down the Paris staircase in Chapter 4. | Unfilled; awaiting URLs/search |
| `wick4-stairs-allies` | Caine helps John's climb and Mr. Nobody's dog intervenes against Chidi in Chapter 4. | Unfilled; awaiting URLs/search |
| `gta6-six-slot-hud` | GTA 6 Extended Look's six-slot wanted HUD; show slots without inventing six active stars. | Unfilled; handled by hand |
| `gta5-police-helicopter` | GTA 5 three-star pursuit with the Police Maverick visible. | Unfilled; awaiting URLs/search |
| `gta5-tactical-suv` | GTA 5 four-star ground NOOSE response in SUVs. | Unfilled; awaiting URLs/search |
| `gta4-helicopter-pair` | GTA 4 six-star pursuit, including its Annihilator air support. | Unfilled; awaiting URLs/search |
| `gta3-tanks-trucks` | GTA 3 six-star military pursuit with Barracks OL trucks and Rhinos. | Unfilled; awaiting URLs/search |

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
3. **Hard needs:** tanks, police helicopter and the optional grieving-man control, with complete
   multiple-choice options/probabilities, chosen answer, correct target and
   pass/fail beside each displayed example, including failures or missing results.
   If no URL is pasted in the grieving-man box, label that control skipped by
   choice; it does not block the gate.

No Stage 3 download, indexing, black-frame filtering, miss audit or confirmation
was run. Those checks wait for the creator's URLs. New files are dual licensed
MIT OR Apache-2.0.
