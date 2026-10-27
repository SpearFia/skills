# Channel document layout

What the DNA writes into `<config>/channels/<id>/`. The six standard documents come from
the app; `packaging.md` and `ideas.md` are added by this skill. Keep each one short and
rule-shaped: the full set goes into every video snapshot and agent brief.

| Document | Read by | Holds |
| --- | --- | --- |
| `channel.md` | every agent | Identity, audience, format, feel, never-does, reading map |
| `ideas.md` | idea agent | Pillars, idea prompt, ranking rubric, covered topics |
| `packaging.md` | idea and thumbnail agents | Title formulas, thumbnail spec, description |
| `style.md` | script, visual script, voice and edit agents | Script, voice, visuals, editing, sound |
| `staples.md` | visual, media and edit agents | Recurring elements and how to reproduce them |
| `tools.md` | voice, media and edit agents | VoiceStudio voice spec and other tool settings |
| `production.md` | orchestrating agent | App workflow (unchanged) and channel-specific stages |
| `lessons.md` | all, after review | Dated entries. DNA adds one entry per version |
| `execution.md` | caption, mix and editing compiler | Validated caption/audio settings and executable recipes; see execution.md in the skill references |

## Rule format

```text
- <What to do, when it applies>. Exception: <when not>. (V03 01:10, V05 · high)
```

`V03` is a video's short ID from the study's `sources.md`; list the ID-to-URL map in the
DNA sources section of `channel.md`. Confidence: `high` (clear in 2+ videos), `medium`
(consistent in a small sample), `low` (hypothesis). Single-video findings go under
`### Observations`.

## `channel.md`

```markdown
# <Channel name>

DNA version: <n> · <date> · reference: <channel name/URL> · corpus: <n videos>

## Reading map
- Ideas: ideas.md, packaging.md · Script: style.md § Script · Visual Script: style.md § Visuals, staples.md
- Voice: style.md § Voice, tools.md § VoiceStudio · Edit: style.md § Editing/Sound, staples.md · Thumbnail: packaging.md

## Purpose and audience
<niche, angle, assumed knowledge, the one-sentence promise>

## Persona
<stance, confidence, humor, how the viewer is treated>

## Format
<runtime range and target, cadence, series, aspect ratio, on-camera presence>

## Feel
<the intangibles in 3-5 lines>
Feel tests:
- <yes/no question a reviewer asks of a draft or cut>

## Non-negotiables
- <rule>

## Never does
- <rule>

## Relationship to Vision
<keep the app's text; add a preferred Vision if one was made>

## DNA sources
| ID | Video | Why chosen |
| --- | --- | --- |
Study folder: <path>. Known gaps: <not observed items>.
```

## `ideas.md`

```markdown
# Ideas

## Pillars
- <pillar>: <what it covers> · e.g. "<title>"

## Idea sources
<where ideas come from; required research step, if any>

## Idea prompt
Generate <N> video ideas for <channel>. For each give: working title (packaging.md formulas),
thumbnail concept (one line), pillar, the hook in one sentence, and why now.
Reject ideas that repeat "Covered" below or break "Off-limits". Then rank them with the rubric.

## Ranking rubric
Score 1-5 each; show the scores, then the total.
- Fit: <what fits this channel, from the DNA>
- Outlier potential: <the traits outliers shared>
- Novelty: not in Covered; a fresh angle if near it
- Feasibility: visuals and facts obtainable with production.md methods; legal risk
- Packaging: a title and thumbnail that work without the other
Drop any idea scoring 1 on Feasibility or Fit.

## Off-limits
- <topic or treatment>

## Covered
- <pillar>: <topic>, <topic>, ...
```

## `packaging.md`

```markdown
# Packaging

## Titles
- Length: <range, median>
- Formulas: "<template>" (<share>), ...
- Rules: <capitalization, numbers, punctuation, trigger words>

## Thumbnails
- Composition / Faces / Text / Color / Devices / Consistency markers: <rules>
- Title–thumbnail split: <rule>
- Concept template: <one-line description an image agent can execute>

## Description
<structure, chapters, sources, links>

### Observations
```

## `style.md`

Replace the app template's three sections with these, keeping their intent.

```markdown
# Style guide

## Script
### Outline
<the reusable section map with runtime shares; variants per format>
### Hook
### Rhythm and language
<wpm, sentence mix, vocabulary, transitions, humor>
### Evidence and claims
### Ending and calls to action
### Sample
<an original 3-5 sentence demonstration on a non-source topic>

## Voice
<voice spec, pace, emphasis, pauses; VO file unit>

## Visuals
<source mix, narration match, on-screen text, captions, graphics, grade, framing, brand>

## Editing
<shot length by section, cut motivation, camera moves, transitions, interrupts, holds,
intro/outro; named recipes>

## Sound
<music by section and bed level, SFX density and triggers, silence, clip audio>

### Observations
```

## `staples.md`

Keep the app's opening paragraph. Add one entry per element:

```markdown
### <element>
Role: <what it does> · Use: <when> · Asset: <path or catalog ID | to source: description>
License/source: <...> · Settings: <...>
```

## `tools.md`

Fill only what the DNA determines: the VoiceStudio target spec (voice traits, rate,
emphasis, what to avoid, VO file unit), marked "needs a voice match" until the creator
records a voice profile. Leave endpoints and workflows to the creator.

## `production.md`

Leave the app's workflow text unchanged. Append:

```markdown
## Channel-specific stages
- <extra stage, e.g. research or fact-check: where it fits, inputs, output>

## Production methods
| Element | Method | Risk / notes |
| --- | --- | --- |

## Media search hints
<query patterns, preferred source order, what to avoid>
```

## `lessons.md`

Append:

```markdown
## <date> · DNA v<n>
Built from <n> videos of <reference> (<IDs>). Not observed: <gaps>. Merge conflicts left for
the creator: <list or none>.
```
