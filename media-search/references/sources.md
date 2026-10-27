# Where to look

Go down the list for the cue's kind and stop at the first source that passes the checks.
All sources here need no API key.

## Routing

| Cue needs | Order |
| --- | --- |
| Anything | 1. Library (`library.jsonl`) |
| Movie, show, game, anime, character, franchise | 2. YouTube: official uploads → clip channels → trailers → others |
| Real people, places, history, science, objects | 2. Wikimedia Commons → 3. Internet Archive → 4. YouTube |
| A still image is enough | Wikimedia Commons → Openverse → a frame grab from a checked clip |
| Mood only ("tense", "epic", "aftermath") | Library → a matching scene from a subject already in the pool → Internet Archive |
| Text, numbers, quotes, comparisons | Don't search: leave for captions/graphics and mark `generated` |

## YouTube (yt-dlp)

### Queries

Write 2–3 phrasings per subject and merge results:

- `<character> <action> scene 4k` · `<character> vs <character> fight scene`
- `<movie> official clip <moment>` · `<movie> trailer 4k`
- `<character> best scenes` (only for mood and subject pools; check for edits)

Add the franchise when names are ambiguous ("Vision Marvel", not "Vision").

```text
yt-dlp "ytsearch15:QUERY" --flat-playlist --dump-json
```

### Prefer

- Official studio and franchise channels, licensed clip channels, official trailers.
- Uploads with 1080p or better (check `formats` in full metadata).
- High view counts as a weak quality signal.

### Reject by title, channel or description (before downloading)

`reaction`, `reacts`, `react`, `review`, `explained`, `breakdown`, `theory`, `edit`,
`AMV`, `fan made`, `fanmade`, `concept`, `AI`, `lyrics`, `meme`, `compilation` (unless
the title shows it's a clean scene compilation), `#shorts`, `shorts`, `TikTok`,
`podcast`, `live`, `stream`, `gameplay commentary`, `ranking`, `top 10`.

Also reject durations under 10 s and vertical videos (height > width).

### Find the segment

- `chapters` in the metadata: pick the chapter matching the subject.
- `heatmap`: the most replayed ranges are usually the action peaks.
- Captions (`--write-auto-subs --skip-download`) to find a named moment.
- Otherwise download a low-resolution preview of a candidate range (`-f "bv*[height<=360]"`),
  sample frames with `scripts/qc.py`, then download the chosen range at full quality.

## Wikimedia Commons

Videos (`filetype:video`) or images (`filetype:bitmap`):

```text
https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=20&gsrsearch=QUERY%20filetype:video&prop=imageinfo&iiprop=url|size|mime|extmetadata
```

Record `extmetadata.LicenseShortName` and `Artist`. Attribution goes in the manifest and
the video description.

## Internet Archive

```text
https://archive.org/advancedsearch.php?q=QUERY%20AND%20mediatype:movies&fl[]=identifier&fl[]=title&fl[]=licenseurl&rows=20&output=json
https://archive.org/metadata/IDENTIFIER
```

Prefer items with a public-domain or Creative Commons `licenseurl`. Download a file
listed under `files`; cut with ffmpeg (`-ss START -to END`).

## Openverse (images)

```text
https://api.openverse.org/v1/images/?q=QUERY&page_size=20
```

Anonymous requests are rate limited; keep them few. Record `license`, `creator` and
`foreign_landing_url`.

## Risk classes

Record one per file in the manifest and library:

| Class | Meaning |
| --- | --- |
| `pd` | Public domain |
| `cc` | Creative Commons or similar; attribution required |
| `fair-use` | Copyrighted film/TV/game footage used under commentary |
| `unknown` | License unclear; use only if the channel allows `fair-use` |

## Library index format

One JSON object per line in `<library>/library.jsonl`:

```json
{"file":"youtube/abc123/abc123_83-101.mp4","source":"youtube","url":"https://www.youtube.com/watch?v=abc123","title":"…","uploader":"…","start":83,"end":101,"tags":["thanos","fight","marvel"],"qc":{"verdict":"pass","width":1920,"height":1080,"notes":""},"risk":"fair-use","used_in":["cwi-ep01"],"added":"2026-10-26"}
```

Tags are lowercase subject words: characters, franchise, action, mood. Search the
index by tags before searching online.
