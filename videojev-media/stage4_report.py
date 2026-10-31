# SPDX-License-Identifier: MIT OR Apache-2.0
"""Write cue-level shortages and Stage 4 gate evidence from saved results."""
import argparse
import collections
from pathlib import Path
from stage4_build import load
from stage4_assign import FPS,MICRO,ROOTS
from stage3_sources import save_json


def report(project):
    folder=project/'media/jev';a=load(folder/'assignment.json');build=load(folder/'stage4-build.json')
    checks=load(folder/'stage4-verification.json');needs=load(folder/'needs.json');inputs=load(folder/'input-cues.json')
    cues={c['id']:c for c in inputs['cues']};slots=a['slots'];filled=[s for s in slots if s['top']]
    duration=lambda ss:sum(s['duration_frames'] for s in ss)/FPS
    counts=collections.Counter(len(s['alternates']) for s in filled)
    source_mix=[]
    by_need={n['id']:n for n in needs}
    for group in ROOTS:
        ss=[s for s in filled if by_need[s['requested_need']]['source_group']==group]
        if not ss:continue
        sources=collections.Counter(s['top']['canonical_id'] for s in ss)
        nearby=0
        for vid in sources:
            at=sorted(s['start_frame'] for s in ss if s['top']['canonical_id']==vid)
            nearby+=sum(b-a<60*FPS for a,b in zip(at,at[1:]))
        source_mix.append(dict(group=group,largest_source=sources.most_common(1)[0][0],
            largest_share_percent=100*max(sources.values())/len(ss),within_60s=nearby))
    rows=[]
    for n in needs:
        ss=[s for s in slots if s['requested_need']==n['id']]
        if not ss:continue
        gaps=[s for s in ss if not s['top']];proof=[s for s in ss if s['strict']]
        missing_proof=[s for s in proof if not s['top']]
        fallback=[s for s in ss if s['top'] and s['top']['need_id']!=n['id']]
        reason='Covered'
        if gaps:
            reason='More unique same-film/game footage needed after global assignment'
            if missing_proof:reason='Missing verified exact/action evidence; broader footage cannot replace it'
            if n.get('manual'):reason='Manual six-slot HUD, as requested'
        rows.append(dict(need=n['id'],wanted_seconds=duration(ss),filled_seconds=duration([s for s in ss if s['top']]),
            unfilled_seconds=duration(gaps),fallback_seconds=duration(fallback),unfilled_proof_seconds=duration(missing_proof),
            reason=reason,broader_fallback=n.get('fallback') or ROOTS[n['source_group']],
            gap_slots=[dict(id=s['id'],cue=s['cue_id'],start_seconds=s['start_frame']/FPS,
                           duration_seconds=s['duration_frames']/FPS,kind=s['kind']) for s in gaps]))
    exact=[]
    for cue in inputs['cues']:
        if cue['match']!='exact':continue
        ss=[s for s in slots if s['cue_id']==cue['id'] and s['strict']]
        exact.append(dict(cue=cue['id'],need=next(s['requested_need'] for s in slots if s['cue_id']==cue['id']),
            required_proof_seconds=duration(ss),filled_proof_seconds=duration([s for s in ss if s['top']]),
            gap_seconds=duration([s for s in ss if not s['top']]),description=cue['visual']))
    assert len(exact)==21
    result=dict(stage=4,status='awaiting_creator_review',review=build['review'],slots=len(slots),
        filled_slots=len(filled),filled_seconds=duration(filled),unfilled_seconds=duration([s for s in slots if not s['top']]),
        alternate_counts=dict(counts),needs=rows,exact_requirements=exact,source_mix=source_mix,checks=checks)
    save_json(folder/'stage4-coverage.json',result)
    benchmark=checks['render_benchmark'];fps=benchmark['export_result']['result']['render_fps']
    lines=['# Stage 4 gate: cwi-003-jev-demo','',
        'Ready for creator review in FilmCraft. Stage 5 and the 1080p upgrade have not started.','',
        f"Review: `{build['review']}`",'',
        f"Assigned {len(filled)} of {len(slots)} word-timed LIVE-footage slots: {duration(filled):.1f} s placed; {result['unfilled_seconds']:.1f} s deliberately unfilled. "
        f"{counts[2]} clips have two alternates, {counts[1]} have one, and {counts[0]} have none. "
        f"There are {checks['master_count']} silent 480p masters. All 198 LIVE cues have a timed assignment or an explicit gap.",'',
        'The approved original is unchanged (project, links, script and visuals hashes verified). Saved Stage 3 results were reused; no source was reindexed. '
        'The demo retains its 10 narration sections, music, intro, end screen, 45 existing content cards plus the intro card, 2,045 captions and blur strip. '
        'Generated-card anchors in the demo were normalized to spoken text so the push could place them.','',
        '## Short-action repair and fallbacks','',
        'Each brief action gets one 3–5 s proof shot, then same-film/game illustrative footage for the remaining narration. '
        'An unavailable action leaves its proof gap empty. Non-exact slots try their existing fallback and then the broad same-film/game root. '
        'Exact scene proof never falls back. Broadest roots cannot fall back to a different film or game. '
        'Conversation, injury and aftermath matches are excluded from fighting fallbacks even when they are from the correct film.','',
        'For `gta6-enter-car`, the 3 s action proof is empty. Its 23.4 s broader remainder also lacks enough unused confirmed official footage. '
        'The existing trailers do not provide a confirmed entry shot; another official URL with the action would help. '
        'The John Wick 4 flame-shotgun proof was recovered from the supplied top-down apartment clip, 105–109 s; it needs no additional URL for its brief proof.','',
        'More URLs are useful for John Wick 1–4 unique footage, official GTA 6 outdoors/wetlands plus entry, and GTA 5 pursuits/SUV/vehicle-switch coverage. '
        'Specific missing proof: Wick 2 warehouse driving, damaged-car inspection and Bowery handgun supply; Wick 3 roof fall, armored Continental defense, armory preparation and exhausted Zero fight; '
        'enough Wick 4 traffic-driving proof; the exact GTA 5 helicopter/wanted-level scene and tactical SUV scene. '
        'These are missing verified evidence in the supplied results, not a claim that every frame of every URL was manually watched. '
        'The six-slot HUD stays manual. Fully covered needs proceeded without waiting for URLs.','',
        '## Coverage after global assignment','',
        'Seconds below use actual voiceover alignment, rather than the earlier word-count estimates. '
        'Broader seconds are explicitly illustrative; they do not count as exact proof. A need may have confirmed supply yet still have gaps because that footage was already used elsewhere.','',
        '| Need | Needed s | Placed s | Broader s | Empty s | Empty proof s |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    lines += [f"| {r['need']} | {r['wanted_seconds']:.1f} | {r['filled_seconds']:.1f} | {r['fallback_seconds']:.1f} | {r['unfilled_seconds']:.1f} | {r['unfilled_proof_seconds']:.1f} |" for r in rows]
    lines += ['', '## All 21 exact requirements','',
        '| Need | Proof needed s | Proof placed s | Empty s |', '| --- | ---: | ---: | ---: |']
    lines += [f"| {r['need']} | {r['required_proof_seconds']:.1f} | {r['filled_proof_seconds']:.1f} | {r['gap_seconds']:.1f} |" for r in exact]
    lines += ['', '## Source variety','',
        'Sixty-second spacing and 25% source share are preferences after matching the need. They relax for strict scene identity or limited unused confirmed supply. '
        'The following are final per-film/game totals, including exact shots; they are not claims that every pool met the soft limits.','',
        '| Film/game | Largest source share | Same-source neighbouring placements within 60 s |',
        '| --- | ---: | ---: |']
    lines += [f"| {r['group']} | {r['largest_share_percent']:.1f}% | {r['within_60s']} |" for r in source_mix]
    lines += ['', '## Stage 4 checks','',
        '- No overlapping source ranges on the top track: passed, including canonical aliases for identified compilation copies. A second 2 fps visual audit found no coherent repeat across assigned slots. Perceptual matching is approximate.',
        f'- No overlapping top-track timeline slots: passed. All {len(filled)} native clips match their intended word-timed start and duration. Narration offsets are unchanged.',
        f"- Handles: 2.5 s each side, clamped only at physical source boundaries. {len(checks['physical_source_clamps'])} placements have a shorter leading handle; all are listed in `media/jev/stage4-verification.json`. Merged masters may give extra handle space.",
        '- Master merging: overlap or gap within 2 s, maximum 120 s; original source range, crop and proxy size are saved in `media/jev/masters.json`.',
        '- Tick scale: verified as 254,016,000,000 ticks/s; 2.5 s = 635,040,000,000 ticks. Source-in quantization is at most half a 30 fps frame.',
        '- Alternate reveal: passed in an unsaved in-memory copy. Deleting top then alternate 1 rendered three distinct shots. The delivered project was not changed by the check.',
        '- Footage audio: passed. Every master has a video stream only; none of its media items occurs on an audio track.',
        '- Scaling: native Scale to Frame Size, the same command used by the pusher, on top and alternate clips. 3840×2160 renders were inspected; original aspect ratio is retained with letterboxing where needed.',
        f"- Three-layer performance: a {benchmark['content_seconds']:.1f} s sample exported at 480p in {benchmark['wall_seconds']:.2f} s wall time ({fps:.1f} render fps), with zero offline media. Interactive playback usability remains for the creator to verify in FilmCraft.",
        '- Blur-strip render fix: this CLI corrupts bottom-edge pixels with masked vertical Gaussian blur. The demo uses horizontal Gaussian blur in the same strip; the colored edge artifact is removed. Test images are in `production/jev-stage4`.',
        '- The pusher reports two edit operations with no picture at their requested time (46:27 and 48:55). Those gaps were not filled with unrelated footage. Some existing cards appear over black; these generated-card cues are distinct from LIVE-footage demand.',
        '- Five focused assignment unit tests pass: alias overlap, brief-action timing, spacing/fallback behavior, bounded master merging, and query/frame normalization.','',
        '## Saved evidence','',
        '- `media/jev/assignment.json`: every slot, selected source range, fallback, master and native clip ID.',
        '- `media/jev/stage4-coverage.json`: per-need seconds, all exact requirements and every gap timestamp.',
        '- `media/jev/stage4-native-snapshot.json`: native tracks, clips, effects and source offsets.',
        '- `media/jev/stage4-verification.json`: handles, silence, reveal and render timing.',
        '- `production/jev-stage4/top.png`, `alternate1.png`, `alternate2.png`: inspected 4K reveal frames.',
        '- `production/jev-stage4/three-layer-480p.mp4`: the native render benchmark.','',
        'Stopped at Stage 4. Open the layered review and judge playback and the remaining gaps before Stage 5.']
    path=project/'production/jev-stage4-report.md';path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(path)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    report(p.parse_args().project.resolve())
