# Channel DNA checklist

Work through every dimension. Each item names what to look for, how to observe or measure
it, and **→** where the resulting rule goes (see `channel-docs.md`). Write `not observed`
with a reason rather than guessing. Skip an item only if it does not apply to the format,
and say so.

Evidence levels: **T** text-observed (titles, transcripts), **M** measured (state the
method), **AV** audio/visual-observed (only when you actually inspected audio or frames).

## Corpus

- [ ] **Outliers:** about 3 long-form videos with the highest views relative to the
  channel's median for a similar upload age. Measure: `view_count` from `uploads.jsonl`
  against the median of videos from the same period.
- [ ] **Typical:** about 3 videos near the median. They show the baseline that outliers
  depart from.
- [ ] **Recent:** at least 1 from the last 3 months. Channels drift, so recent habits win
  over old ones when they conflict.
- [ ] Exclude Shorts, livestreams, collabs and sponsored-only uploads unless that is the
  target format. Study Shorts as a separate format if the channel relies on them.
- [ ] Keep one video back as a held-out check (see **Validation**).
- [ ] Record in `sources.md`: ID, title, runtime, views, upload date, why chosen, caption
  source and language, and coverage (text, audio, frames).

## 1. Identity and audience → `channel.md`

- [ ] **Niche and angle:** what the channel covers, and the angle that sets it apart from
  others in the niche. (T)
- [ ] **Audience:** assumed knowledge (newcomer, fan, expert), age range if evident,
  shared references and in-jokes. Look at what goes unexplained. (T)
- [ ] **Channel promise:** what a viewer reliably gets (a verdict, a laugh, a ranking,
  being caught up on news, relaxation). Write it in one sentence.
- [ ] **Persona:** narrator stance (expert, fan, skeptic, guide, comedian), confidence,
  warmth, sarcasm, and how they treat the viewer. Describe the broad character, not a
  biography or an impersonation.
- [ ] **Values and tone boundaries:** what they take seriously, what they mock, what they
  never joke about, and how much profanity they use.
- [ ] **Never does:** the habits clearly absent (no face cam, no sponsor reads, no
  clickbait questions, no music under explanations). Absence is DNA too.

## 2. Format and cadence → `channel.md`

- [ ] **Runtime:** range and median, for outliers and for typical videos. (M)
- [ ] **Upload cadence:** videos per week or month in the last 6 months. (M)
- [ ] **Series and recurring formats:** named series, rankings, "vs" videos, explainers,
  news roundups, and the share of each. (T)
- [ ] **Aspect ratio and resolution;** Shorts strategy, if any.
- [ ] **On-camera presence:** none, voice-only, face cam, avatar or mascot.

## 3. Topics and ideas → `ideas.md`

- [ ] **Topic pillars:** 3–7 recurring topic families, each with example titles.
- [ ] **Outlier pattern:** what outlier topics share (timeliness, a famous subject,
  conflict, a surprising claim, nostalgia) that typical ones lack.
- [ ] **Idea sources:** news cycle, fan questions, trends, evergreen lore, comment
  requests. Note whether the channel needs a research step (news channels do).
- [ ] **Already covered:** a compact list of topics already done, grouped by pillar. The
  full title list stays in the study folder (`uploads.jsonl`).
- [ ] **Off-limits:** topics or treatments the channel avoids.
- [ ] **Ranking rubric:** fill the rubric in `channel-docs.md` with this channel's
  evidence (what "fit", "outlier potential" and "feasibility" mean here).

## 4. Packaging → `packaging.md`

### Titles

- [ ] Length in characters and words (range and median). (M)
- [ ] Title formulas, written as templates: "X vs Y: who wins?", "Why X is ...",
  "Ranking every X". Give the share of each and whether outliers favor one. (T)
- [ ] Capitalization, numbers, brackets, emoji and punctuation habits.
- [ ] Emotional trigger: curiosity gap, conflict, superlative, fear, nostalgia, humor.
- [ ] Recurring words that appear across titles.

### Thumbnails (AV, from the downloaded thumbnails)

- [ ] **Composition:** subject count, placement, close-up or wide, background type.
- [ ] **Faces:** a real face, a character face or none; expression type.
- [ ] **Text:** word count (often 0–4), font family style, color, outline or shadow,
  placement. The text must add to the title, not repeat it.
- [ ] **Color:** dominant palette, contrast level, saturation, consistent brand colors.
- [ ] **Graphic devices:** arrows, circles, "vs" splits, before/after, blur, glow,
  stickers.
- [ ] **Consistency:** can you tell it's this channel without the name? Which elements
  make that true?
- [ ] **Title–thumbnail relationship:** how the two divide the work (the thumbnail shows
  the stakes, the title names them).
- [ ] Outlier thumbnails vs typical: what differs.

### Description and metadata

- [ ] Description structure: summary, chapters, sources, links, hashtags.
- [ ] Chapters used or not, and how they are named.
- [ ] Pinned comment habits, if visible.

## 5. Script → `style.md` § Script

For full depth use the `learn-channel-scripts` analysis rubric when available. Minimum:

- [ ] **Hook (first 15–30 s):** type (cold open, claim, question, scenario, outcome
  preview). Time until the premise is clear, and until the first real payoff. (T, M from
  caption timestamps)
- [ ] **Title promise:** where and how the opening confirms what the title and thumbnail
  promised.
- [ ] **Macro structure:** a section map per video with the share of runtime for setup,
  body, complications, verdict and outro. Write it as a reusable outline, with variants if
  the channel has more than one format.
- [ ] **Re-hooks and open loops:** how often a question is opened and when it is paid off.
  Report ranges, not a universal "every N seconds".
- [ ] **Narration rate:** estimated words per minute, method stated (caption words over
  elapsed narration time). (M)
- [ ] **Sentence rhythm:** short and long sentence mix, fragments after dense lines, use
  of questions, lists and asides. Use authored or corrected sentences only; auto-captions
  are not sentences.
- [ ] **Vocabulary:** formality, slang, niche jargon and when it gets defined, intensifiers,
  hedges, contractions, pronouns (I, we, you).
- [ ] **Transitions:** how sections connect (consequence, escalation, callback,
  objection). Record the function, not just stock phrases.
- [ ] **Humor:** type (understatement, absurd comparison, meme reference, callback),
  frequency, and whether it works without the visuals.
- [ ] **Argument and evidence:** claim → evidence → consequence pattern, how uncertainty
  and counterarguments are handled, source citation habits.
- [ ] **Ending and calls to action:** verdict, recap, tease of the next video, subscribe
  prompt, and its placement. Sponsor read placement and style.
- [ ] **Signature devices:** recurring segment names, sign-offs, structural tricks.
  Describe their function. Do not copy catchphrases into rules.
- [ ] **Script length:** word count against runtime, so the script agent can budget.

## 6. Voice and delivery → `style.md` § Voice, voice settings in `tools.md`

- [ ] **Voice type:** pitch range, gender presentation, age impression, accent. (AV)
- [ ] **Energy and pace:** steady or dynamic, and where it speeds up or slows down. (AV)
- [ ] **Emphasis:** which words get stressed (contrasts, numbers, consequences) and how
  (pitch, volume, pause before). (AV only)
- [ ] **Pauses:** dramatic pauses and silence before reveals. (AV)
- [ ] **Recording character:** dry or roomy, compressed, any processing effects.
- [ ] **Text-to-speech fit:** write the VoiceStudio target as a spec: voice traits,
  speaking rate, and what to avoid (over-dramatic reads, flat lists). Mark it
  "needs a voice match" until the creator picks a voice profile.
- [ ] **VO segmentation:** the natural unit for VO files (section, paragraph, sentence),
  judged from where the edit cuts. Recommend one unit for the VO agent.

Without audio access, mark this whole section `not observed (text only)` and give only
proposals, labeled as proposals.

## 7. Visual language → `style.md` § Visuals

- [ ] **Visual source mix:** the share of stock footage, film or TV clips, gameplay,
  screen recordings, memes, generated images, motion graphics, maps and charts, photos,
  face cam. Estimate from sampled frames. (AV, M with sample size)
- [ ] **Visual-to-narration match:** literal (shows exactly what is said), loose (topic
  mood), ironic (contradicts it for a joke). The share of each matters to the media search
  agent.
- [ ] **On-screen text:** frequency, font style, color, size, position, animation (pop,
  type-on, slide), keyword highlighting.
- [ ] **Captions or subtitles:** none, burned-in full captions, or keyword-only; style.
- [ ] **Graphics and data:** chart style, map style, lower thirds, labels, number reveals.
- [ ] **Color and grade:** neutral, saturated, desaturated, or a consistent tint;
  vignettes, film grain.
- [ ] **Framing:** zoom level, crop style for clips, borders, picture-in-picture, split
  screens.
- [ ] **Brand elements:** logo bug, mascot, color palette, recurring backgrounds.

## 8. Editing rhythm → `style.md` § Editing

- [ ] **Average shot length:** median and range, per section type (hook, body, climax).
  Measure from scene-cut detection; state the threshold. (M)
- [ ] **Cut motivation:** cuts on sentences, on beats of the music, on jokes, or freely.
- [ ] **Camera moves:** digital zooms, punch-ins, Ken Burns pans on stills, shake. How
  often, how fast, and on what trigger (an emphasized word, a reveal, a joke).
- [ ] **Transitions:** hard cuts vs effects (whip, zoom, glitch, fade); which ones and
  how often. "Mostly hard cuts" is a valid and useful finding.
- [ ] **Pattern interrupts:** sudden zooms, meme inserts, sound stings, freeze frames,
  black frames. Frequency range.
- [ ] **Holds:** when a shot stays still, and for how long (for example, on charts while
  explaining).
- [ ] **Intro and outro:** length, branded sequence or none, end screen layout.
- [ ] Express what you can as recipes or catalog looks (a named combination of effect,
  timing and trigger), so the editing agent applies them instead of interpreting prose.

## 9. Sound design → `style.md` § Sound

- [ ] **Music:** genre and mood per section type, whether it changes with sections, bed
  level under VO (barely audible, present, prominent), and whether it drops out for
  emphasis. (AV)
- [ ] **Sound effects:** density (per minute, approximate), types (whooshes, risers, hits,
  meme sounds, UI clicks) and triggers.
- [ ] **Silence:** used for punchlines or reveals or not at all.
- [ ] **Clip audio:** whether source clips keep their audio, ducked or muted.
- [ ] **Loudness:** consistent or dynamic. Measure integrated LUFS only if the audio is
  available, and state the tool.

## 10. Recurring elements → `staples.md`

- [ ] Intro and outro sequences, logo stings, transitions, lower thirds, fonts, music
  themes, signature SFX, mascots, segment cards.
- [ ] For each: what it is, when it is used, and how to reproduce it: the actual asset
  path or catalog ID if the creator owns a matching one, otherwise "to source" with a
  description and a free or generated alternative.
- [ ] Never list the reference channel's own assets as usable. Record what to build
  instead.

## 11. Intangibles → `channel.md` § Feel

What makes a video feel like this channel after all the measurable parts are matched:

- [ ] The viewer's relationship to the narrator (a friend explaining, an expert ruling, a
  fan arguing).
- [ ] The emotional arc of a typical video (curiosity → tension → satisfaction, or calm
  throughout).
- [ ] Density: how much happens per minute, and whether it feels relaxed or relentless.
- [ ] Polish level: raw and scrappy, or highly produced. Copying the wrong polish level
  breaks the feel.
- [ ] Three to five "feel tests": yes/no questions a reviewer can ask of a draft or rough
  cut ("Would the narrator say this sentence out loud?", "Is there a visual change at
  least every N seconds in the body?").

## 12. Production feasibility → `production.md` § Channel-specific stages

For each major element found above, how our pipeline produces it:

- [ ] **Method:** reuse a staple, free stock, search and download, ComfyUI generation,
  Remotion or motion graphics, VoiceStudio, or manual work.
- [ ] **Difficulty and risk:** hard to replicate, slow, or legally risky (copyrighted film
  or sports footage, music). Flag Content ID and reused-content risks plainly.
- [ ] **Extra stages:** research, fact-check, data gathering, licensing checks. For
  example, a news channel needs a sourced research step before ideas.
- [ ] **Media search hints:** query patterns that would find this channel's kind of
  visuals, and the preferred source order.

## Validation

- [ ] Check the rules against the held-out video. Revise rules it contradicts; do not
  bend the video to fit.
- [ ] From the guides alone, a hand-test hook and three titles on an uncovered topic
  read like the channel without copying it.
- [ ] Every rule has evidence and a confidence label. Single-video findings are under
  **Observations**, not **Rules**.
