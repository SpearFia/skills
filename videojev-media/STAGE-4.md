# Stage 4: timed assignment and FilmCraft layers

The demo review is ready for the creator's Stage 4 gate. The approved original,
Windows model environment and completed Stage 3 source results were preserved.

Review: `D:\SpearFia\projects\cwi-003-jev-demo\sync\review-plan-1793443281-layers.fcproj`.

Coverage and checks: `D:\SpearFia\projects\cwi-003-jev-demo\production\jev-stage4-report.md`.

- 422 top clips, 147 handled 480p masters, 262 alternates. Two alternates exist
  under 128 clips, one under six. Confirmed supply runs out elsewhere.
- All 198 LIVE cues have precise narration timing and assigned slots or explicit
  gaps. There are 1,432.2 s placed and 953.2 s unfilled. Exact scenes stay strict.
- Brief actions use one 3â€“5 s shot, with broader same-film/game footage for the
  remainder. Missing action proof is left empty, including GTA 6 car entry.
- No overlapping source or timeline intervals on the top track. A visual audit
  of the selected footage also found no coherent repeat across copies.
- Handles are 2.5 s, clamped to physical source boundaries. Merged masters keep
  source ranges, crops and proxy sizes for the later upgrade.
- Native readback verified every slot. Deleting the top and then alternate 1
  revealed three distinct shots. Every master and its placements are silent.
- Native frame-size scaling retains aspect ratio in 3840Ã—2160. The inherited
  blur strip uses horizontal Gaussian blur to avoid a vertical-blur edge defect
  in this version of the headless renderer; the Rust pusher is unchanged.
- The two-second, three-layer 480p preview export reached 45.5 fps with no
  offline media. Interactive FilmCraft playback remains the creator's check.
- Ten focused tests passed, including assignment safety and existing needs
  parsing. Stage 5 and the 1080p upgrade have not started.

The scripts reuse the existing project-scoped `pool.links_add` and installed
FilmCraft MCP commands. The connected project tools point at the original and
were not used for mutations. The demo keeps narration, music, 45 existing
content cards plus the intro card, captions, intro and end screen. Only its
generated-card anchor formatting was repaired; no narration was rewritten.

```powershell
py -3.11 videojev-media/jev.py assign --project D:\path\to\demo
py -3.11 videojev-media/jev.py build --project D:\path\to\demo
py -3.11 videojev-media/stage4_verify.py --project D:\path\to\demo
py -3.11 videojev-media/stage4_report.py --project D:\path\to\demo
py -3.11 -m unittest discover -s videojev-media -p test_stage4.py
```

Build refuses the approved original and an existing review output. Cached link
maps must agree with the saved assignment. Review files from earlier passes
remain saved. Spacing and source share are soft preferences; the coverage
report shows where limited matching supply required relaxing them. Perceptual
duplicate matching is approximate, and full interactive playback was not tested.
