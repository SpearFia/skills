---
name: plugin-builder
description: Build a Spear Fia effect plugin (DCTL, OFX or WGSL) from an idea to a tested, profiled plugin with a capability descriptor. Use when asked to make a new effect, port one to another format, or make a slow effect real-time.
---

# Plugin builder

Build effects in this order. Don't skip ahead: features added before the minimal build is
fast are the usual reason a plugin ends up unusable in real editing.

1. **Algorithm.** Write the math in plain terms first: inputs, outputs, coordinate
   conventions, edge cases. Decide which parts belong in `plugins/shared/`.
2. **Minimal build.** Start from `templates/` (`dctl-skeleton.dctl` or `ofx-skeleton/`).
   Implement only the core transform with one or two parameters.
3. **Test.** Render fixed frames and compare them to goldens with `plugins/test-harness`
   (see `verify/README.md`). Check edges, off-center targets and the extremes of every
   parameter.
4. **Profile.** Measure playback on real footage at the target resolution and frame rate,
   not just scripted renders. Compare against a passthrough build. Read
   `checklists/performance.md`.
5. **Features.** Add the rest one at a time, re-profiling after each. Follow
   `checklists/parameter-ux.md` for every parameter.
6. **Descriptor.** Write `<plugin>.asset.json` against the `asset` schema: hosts,
   capabilities (typed inputs, `requires`, `binds`), license, source and hash. Add a
   recipe if the effect is mostly used in combination.

Report honestly at each step: what was verified on real footage, and what was not.
