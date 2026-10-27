# Production contract

Licensed under MIT OR Apache-2.0.

Use `jobs_plan`/`jobs_run`/`jobs_status` when the connected Spear Fia exposes them. Discover
their schemas first. A search/pool job records a stable ID, source cue IDs, exact required
match level, source policy revision, bounded queries, dependencies and output checks.
Keep a deterministic candidate ledger in `media/search-state.json`: source ID and range,
attempted query, outcome, rejection reason and QC artifact path. Save it after each
candidate, using an atomic replacement. A rerun first checks this ledger and the library.

Never reuse solely because a filename exists. Match the request/cue revision and source
range, verify the file hash and QC outcome, then reuse its saved link. Recheck source
policy and exact/subject/mood acceptance. A policy change invalidates the affected choice.
Pool choices save time, but each cue needs its own confirmed saved narration attachment.

The project manifest entry needs cue ID, link ID, file SHA-256, source ID/URL and original
source range, any local trim/crop, license/attribution, requested and achieved match,
QC measurements, visual verdict, reviewer and status. `candidate`, `accepted`, `rejected`
and `unresolved` are distinct. A completed download is still a candidate. Preserve source
times when trimming, so provenance and later re-editing remain reproducible.

Measure required footage against aligned narration intervals when available. Total clip
seconds alone do not establish picture coverage: flag gaps, exhausted clips, overlaps,
intentional holds and repeated segments. Resolve anchors after narration edits. Stills
can deliberately cover a time interval; temporal video checks do not apply to them.

`production/media-report.md` lists per-cue accepted links, unresolved matches, source
variety, coverage issues and needed creator decisions. Return `needs_input`/`blocked`
when requirements remain unmet; never loosen them to make a stage report complete.

`jobs_run` is asynchronous over MCP/HTTP. Poll `jobs_status` until `running` is false,
inspect every requested job and worker error, then verify the expected files and links.
A returned `started` acknowledgement does not complete a production stage.
