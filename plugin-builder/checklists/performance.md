# Performance checklist

- [ ] Measured playback fps on real footage at the target resolution and frame rate
      (e.g. 4K 59.94), not only ms per frame in scripted renders. The two disagree.
- [ ] Compared against a passthrough build of the same plugin, to separate the host's
      overhead from the effect's cost.
- [ ] Texture reads minimized: no redundant `_tex2D` calls, RGB-only path when alpha is
      unused, no per-pixel loops over neighbors unless the feature needs them.
- [ ] Optional stages (blur, sharpen, glow) cost nothing when they are off: branch on the
      parameter before doing the work.
- [ ] Values that are constant per frame (easing, timing) are computed once, not per pixel.
- [ ] Fusion-based versions: expressions are evaluated on every reference, so compute
      shared values once in a modifier. If Fusion still can't play back in real time on
      the Edit page, move to DCTL or OFX.
- [ ] Kept each scripted render or MCP call small. Long scripted renders and huge
      expressions have crashed Resolve.
