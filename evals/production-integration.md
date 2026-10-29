# Production skill integration review

Licensed under MIT OR Apache-2.0. Reviewed 2026-10-27 against the CLI coordinator.

## Findings and changes

1. Media search contradicted itself on exact matches: the main workflow reserved exact
   cues for specific evidence, while checks.md permitted subject substitutes. A mismatch
   now remains unresolved until the creator changes the requirement.
2. Channel DNA's relative study default collided with its prohibition on storing research
   inside a project, because coordinated agents run from the project directory. Coordinated
   runs now require an external study root.
3. Flat upload metadata was treated as sufficient for age-adjusted view comparisons.
   Missing views/dates must now be fetched in a bounded pool or reported as unknown.
4. DNA described editing, captions and sound in prose without an executable contract.
   execution.md now carries validated style JSON and actual recipe capability IDs.
5. Media search had no persistent candidate ledger or output proof, and its chapter total
   could hide narration gaps. The production contract adds hashes, cue/link IDs, attempted
   candidates, retained rejections and interval coverage checks.
6. Coordinator report paths differed from the skills. The two reviewed skills now produce
   production/channel-dna.md and production/media-report.md while retaining their real
   guides/manifests as deliverables.
7. QC swallowed some failed ffmpeg calls and applied temporal assumptions to stills.
   Decoder failures must fail the check; stills need a separate measurement branch.
8. The generic media skill claimed source acceptance for every channel. Source choices
   now come from the current channel's saved policy, preserving prior explicit choices.

## Behavioral cases

- Exact evidence cue; only a related subject clip is available: save candidate and leave
  cue unresolved, rather than reporting success.
- Restart after three accepted clips and two rejected candidates: verify hashes and
  reuse the accepted links; do not redownload the rejected ranges.
- Caption-only evidence for a channel: voice, cut rhythm and sound remain unobserved;
  proposed executable settings are identified for creator review.
- A narration change moves or deletes a cue: repair its attachment and invalidate
  affected choices before generation or assembly.
- ffmpeg cannot decode a candidate: no empty "pass" result. A still image is inspected
  without applying video duration/bitrate/temporal-logo thresholds.
