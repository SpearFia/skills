# Quality checks

`scripts/qc.py` measures; you decide. Run it on every downloaded segment, then look at
the sampled frames.

## Automatic (from `qc.py`)

| Field | Reject when | Notes |
| --- | --- | --- |
| `height` | < 720 | Allow 480 only for a `mood` cue with nothing better, and say so |
| `bits_per_pixel` | < 0.03 | Low bitrate for the size: likely re-encoded or upscaled |
| `duration` | < 2 s | Too short to use as a shot |
| `black_ratio` | > 0.3 | Mostly black: fade, title card or broken file. Trim if the rest is usable |
| `crop` | not null | Letterbox or pillarbox found: crop to it when copying into the project |
| `static_corners` | any corner listed | A corner that never changes while the picture moves: likely a logo or watermark. Confirm visually: a locked-off shot of a detailed, still background (a wall, a skyline) flags too |
| `frozen` | true | The picture barely changes: a still or a frozen stream. Fine for stills, bad for "fight scene" |

## Visual (look at 3–4 sampled frames)

Reject, or trim to a clean range, when you see:

- A watermark, channel logo or network bug that would show in the final frame (crop it
  out only if it sits in a letterbox bar that gets cropped anyway).
- Burned-in subtitles or captions (the video adds its own animated captions).
- A reactor's face cam, picture-in-picture, borders, frames, split screens.
- Text overlays, emoji, arrows, "SUBSCRIBE", end cards.
- Visible AI artifacts or fan-made CGI passed off as the real thing.
- Content that doesn't show the cue's subject at the cue's match level.
- Graphic gore or sexual content beyond what the channel shows.

Write the verdict in the manifest: `pass`, `trimmed (<start>-<end>)`, or `reject
(<reason>)`. Keep rejects in the library index with the reason so they aren't retried.

## Match level achieved

Record what the clip actually delivers:

- `exact`: the requested moment itself.
- `subject`: the right subject in another context (Thanos fighting someone else).
- `mood`: only the feel.

A cue asking for `exact` and getting `subject` is fine to link, but list it in the report.
