# Prompting cheat sheet

Licensed under MIT OR Apache-2.0.

Read this, not the full research report (`C:\Users\caesa\reports\ASMR sound and visual
catalog.md`, 65 KB). The report is the evidence; this is what production needs. For
pairing ideas, grep the report's catalog by family heading (`### Slime`, `### Sand,
powder and chalk`, …) and read only that family.

## Reference image (MOSS-Image, cfg 1.0, 1792×1024 → 1344×768)

The reference image sets the look more than the video prompt does. Name the generative
system, the medium and the light gradient, never the real object ("lava", "slime" pull
toward photos). Negative prompts do nothing at cfg 1.0.

```text
A full composition, strict top-down orthographic view of a flat matte pure black background,
no perspective, no horizon. {SYSTEM: "A branching network of emissive filaments like a
Lichtenberg figure"} {ORIGIN: "spreads from a single hairline fissure at the centre"}.
{LIGHT GRADIENT: "white-gold hot cores, molten orange midtones, ember-red tips fading into the
black"}. {STRUCTURED DETAIL: "fine secondary forks, crisp hairline edges"}. {NEGATIVE SPACE: "the
network covers the central third; the rest is clean, empty pure black"}. Flat 2D generative art,
{MEDIUM: neon line art / risograph flat colour / cel-shaded / gouache flat fills}, luminous, high
contrast, intricate yet clean, crisp sharp edges, smooth clean gradients, no text.
```

- One clear origin for motion to travel from; 30–50% empty black.
- Structured detail (filaments, bands, isolines), not grain or glitter: grain boils.
- Never: photograph, realistic, macro, lens, depth of field, cinematic, 4k, horizon, a
  ground colour other than pure black, colour names that are objects (rose, honey).

## Loop clip (MiniMax H3, 4-step turbo, 8 s, first = last frame)

Describe the motion path with timestamps, not the picture. One dominant motion. Static
top-down camera. End on the reference image.

```text
2D-animated abstract generative art, flat graphic, emissive light. Strict top-down view of the
{structure} on the pure black background of <Picture 1>; the camera is a static shot looking
straight down, no cuts. {MOTION from 0 s: "a dense shimmer of tiny beads races outward along
every filament"}. At {t1} seconds {event 1}. At {t2} seconds {event 2}. {between events: steady
secondary motion}. From 7.0 seconds {settling}, and at 8.0 seconds the frame settles exactly into
<Picture 1>. The background stays pure black throughout; no text, no watermark, no camera movement.

overall_soundscape: {1–2 sentences: the sound, each event audible}.

non_diegetic_music: N/A
```

Motions that loop cleanly, best first: light travelling along a fixed structure; a
repeating pattern sliding by exactly one tile; an n-fold pattern rotating by 360/n degrees;
events appearing and fading at steady density. Big displacement (growth, spreading) needs
a middle keyframe or it reads static. QC rejects motion < 0.06: ask for strong verbs
("races", "surges", "sweeps across the whole frame"), not "gently".

## Segment sound (Stable Audio 3, cfg 1.0, 8 steps, 90–180 s chunks)

```text
TrackType: SFX, {source}, {action + manner + rate in plain words}, {texture: soft/crisp,
wet/dry, low-pitched}, close-mic foley, close-up, stereo, quiet room tone, high quality,
continuous, steady
```

- 40–120 words, source and action first (the encoder truncates at 256 tokens).
- Rate in words ("about one every two seconds"), never BPM.
- Avoid music tags: relaxing, soothing, dreamy, meditation, lofi, cinematic, ambient.
- **Sparse sounds fail QC.** Single crunches with silence between them trip the dropout
  and sudden-peak checks (ASMR 001: 7 of 15 chunks re-rolled). Ask for a continuous texture
  ("continuous slow crumbling with frequent soft crunches") and put rare accents in their
  own short one-shot layer.
- Beds: "TrackType: SFX, soft steady rain on a window, distant, continuous, steady" or
  "TrackType: Music, ambient drone pad, slow evolving warm textures, no melody, no drums".
