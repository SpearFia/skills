# Verify with the test harness

1. Add cases to `plugins/test-harness/` for the new plugin: fixed parameters, a fixed
   source frame, and a tolerance.
2. Render each case. For Resolve DCTLs, render single frames through the render queue:
   `ExportCurrentFrameAsStill` has returned stale frames. A texture-sampling DCTL only runs
   in the ResolveFX DCTL plugin, not as a node LUT.
3. Make sure no other Edit-page effects are on the test clips: they're invisible to the
   scripting API and contaminate renders (and `DuplicateTimeline` copies them).
4. Compare with the goldens. Commit new goldens (Git LFS) only after checking them by eye.
5. Then check playback on real footage by hand; the harness can't measure that.
