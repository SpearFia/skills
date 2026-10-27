# Executable channel style

Licensed under MIT OR Apache-2.0.

Prose explains a channel's choices. Production also needs exact settings it can execute.
Add `execution.md` to the shared channel guides with one fenced `spearfia-style` JSON
block matching Spear Fia's `production-style` schema. The project snapshot carries this
block; a reviewed `production/style.json` can override it for a particular video.

Record caption font, pixel size for the target resolution, colors, normalized placement,
words per line/group, gap and character limits, emphasis policy and supported animation
mode. Record voice/music/SFX gains in dB, fade duration and ducking depth/attack/release.
Use only supported modes; do not convert an impression such as "energetic" into invented
measurements. Label proposed values next to the block and request creator review at the
normal DNA gate. If captions or music are absent in observed material, encode that choice.

Named recipes identify actual capabilities and parameters. FilmCraft native capabilities
use `filmcraft/<effect>#apply`; animated values contain measured or proposed `from`/`to`
values. Plugin source files alone do not establish a loadable FilmCraft capability.
Record unsupported plugin dependencies instead of claiming the recipe can run.

Validate the profile with `spearfia style validate`. Every high-level editing rule should
point to a recipe, a caption/mix setting, or an explicitly manual treatment. A tiny
synthetic caption/motion/audio sample is a better execution check than another prose
summary. Review it alongside the held-out video and hand-test hook/title examples.

For coordinated runs, put the study root on the media drive and explicitly outside the
project and channel library. The CLI agent's working directory is the video project, so
the old relative `dna-study/` fallback is unsuitable there. Record the study root, corpus
IDs, guide revisions, conflicts and proposed settings in `production/channel-dna.md`.
Keep research media and large ledgers outside the compact channel snapshot.

`jobs_run` is asynchronous over MCP/HTTP. Poll `jobs_status` until `running` is false,
inspect every requested job and worker error, then verify the expected files and links.
A returned `started` acknowledgement does not complete a production stage.
