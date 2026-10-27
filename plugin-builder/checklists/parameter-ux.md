# Parameter UX checklist

- [ ] Every parameter has a plain label and a sensible default; the effect looks right
      when dropped on a clip with no changes.
- [ ] DCTL labels contain no parentheses, and tooltips match the label exactly.
- [ ] DCTL color pickers can't be read as `.x/.y/.z`: use three sliders for RGB.
- [ ] One animatable "progress" (0 = off, 1 = full) drives the whole effect, so users
      keyframe one value instead of five.
- [ ] Coordinates are documented: in DCTL `p_Y = 0` is the top row; in the UI, say which
      corner (0,0) is.
- [ ] Ranges are clamped to what looks good; extreme values don't produce garbage.
- [ ] Group parameters by task (animation, target, shape, outline, background) in the
      order a user reaches for them.
- [ ] After any DCTL edit, press Reset next to the DCTL list: the plugin caches its compile.
