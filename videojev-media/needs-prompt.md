# One-time needs draft for the John Wick demo

Input: the approved cwi-003 script and Visual Script, read-only. Use the indexed
LIVE-footage cue snapshot from `pool.all_cues`; generated cards remain untouched.
This prompt is applied once by the coding assistant to write the frozen draft.
Checklist generation and all later pipeline commands make no LLM calls.

Write about 30–50 reusable visual needs. Merge cues wanting the same visible
picture. Keep footage from different films/games distinct when the narration or
an exact Visual Script requirement names that source. Retain each exact VISUAL
and continuity restriction in the source snapshot for later review/assignment.

For each need provide:

- Stable kebab-case `id`, readable `label`, indexed `cue_indices` from the snapshot.
- `query`: one plain sentence describing a visible event/state, without names,
  story context, costume trivia, negation or an abstract conclusion.
- `variants`: at most one alternate wording of that same visual need.
- `confirm`: a question, one correct visible description, and two plausible
  distractors. The worker later adds "None of these." and shuffles with a fixed seed.
- `generic`: whether this is broad illustrative coverage, and `fallback`: a
  broader compatible need ID or null. Exact evidence must never silently fall back.
- `source_scope`: the actual film/game and any source restrictions. These are
  for the creator; proper names belong here or in labels, never model queries.

Include tanks and a police helicopter as narration needs. Include a grieving man
as a `review_only` control with no cue demand: the approved narration does not
request grief. Keep historical games and their individual military responses
separate. Official GTA 6 footage supplies setting/visible promotional evidence;
do not turn the hypothetical six-star scenario into a confirmed gameplay claim.

Map every LIVE cue once, with no invented IDs and no generated-card IDs. Use
the cue's principal approved visual treatment; preserve the entire exact VISUAL
and helper/evidence-label restrictions for checking the final sequence. Mark
hard needs for the Stage 3 gate. Expand indices to actual cue IDs deterministically.

Stage 2 estimates seconds with the existing pool narration rate, 2.6 words/sec,
and labels them estimates. Exact word-timed assignment comes later. The creator
only pastes URLs under need headings; never seed URLs or start indexing here.
