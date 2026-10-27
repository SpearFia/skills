# Eval: Focus Loupe from scratch

## Prompt

Build a DaVinci Resolve effect that zooms into a target point, either full frame or
inside a circular or rectangular loupe, animated by one progress value. It must play back
4K 59.94 footage at full speed on the Edit page.

## Done looks like

- Builds in the ResolveFX DCTL plugin with no errors.
- Plays back at about 59 fps on 4K 59.94 footage.
- Circle, rectangle and full-frame modes are correct at off-center targets.
- A descriptor that validates against the `asset` schema.

## Failure notes

- A Fusion macro version was correct but ran at ~13 fps on the Edit page: too slow.
- DCTL v1.0 failed to build: a color picker was read as `.x/.y/.z`.
