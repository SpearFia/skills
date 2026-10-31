# SPDX-License-Identifier: MIT OR Apache-2.0
"""Render approved-query evidence without interpreting or changing any beat."""
import argparse
import collections
import html
import re
from pathlib import Path

from script_first import read,questions
from stage3_index import union
from stage3_review import sheets,source_links
from stage3_sources import save_json


def render(project):
    root=project/'media/jev/script-first';folder=root/'query-results'
    document=read(root/'beats.json');qs=questions(document)
    candidates=read(folder/'cached-choices.json')+read(folder/'candidates.json')
    representatives=read(folder/'representatives.json');audit=read(folder/'miss-audit.json')
    all_rows=read(root/'score-reuse.json')['rows']+read(folder/'score-windows.json')
    videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
    target=project/'production/jev-script-query-review';target.mkdir(exist_ok=True)
    doc=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Approved specific-query review</title>',
        '<style>body{font:16px/1.5 system-ui;max-width:1400px;margin:24px auto;padding:0 16px}img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccc;text-align:left}summary{cursor:pointer;padding:12px;background:#edf2f5}.note{background:#fff0c0;padding:16px}input{padding:10px;font:inherit;width:90%;margin:12px 0}</style>',
        '<h1>Specific-query review gate</h1>',
        '<p class="note">The approved sentence beats are unchanged. Scores are model confidence. Named scenes and identities require creator review. Cached pairs were not resubmitted. General pools use all eligible group footage. No assignment, timeline build or Stage 5 operation occurred.</p>',
        '<p>Blocked: <code>tJbzMqJGH4k</code> is age-gated; paste a replacement. No bypass or retry.</p>',
        '<p>Sheets include the highest cell, random above-threshold samples and nearest below-threshold samples. The threshold is shown for each round. Choice results use their actual source context; missing choices are marked, never invented.</p>',
        '<p>The old grieving-man control is inactive because it creates no approved script beat. Its <a href="../jev-review/review.html">earlier results remain saved</a>.</p>',
        f'<p>Independent 2 fps miss audit: {len(audit["sources"])} long sources; {len(audit["dropped_matches"])} model-confirmed sampled spans outside coarse retention. This is a sampled audit of new questions, not exhaustive recall.</p>',
        '<input id="find" type="search" placeholder="Filter by query, film/game, scene or beat ID" aria-label="Filter queries">']
    coverage=['# Script-first specific-query coverage','',
        f"Review before assignment. All {document['counts']['sentences']} approved sentence beats remain unchanged. The 10 general pools are ready. No narration-length or 3× duration target is applied to a literal query.",'',
        '[Open the review sheets](../../../../production/jev-script-query-review/review.html).','',
        'Cached numeric scores are reused, not old scene verdicts. Native question vectors are kept separate. New literal candidates receive a mechanical multiple-choice check. Up to three high-scoring, spaced main confirmation samples per new video/question pair are checked; all fine-window scores remain saved. Random/near-miss hard-need samples can add choice checks.','',
        'A missing model-confirmed sample does not establish that the shot is absent from every video, especially for cached pairs with untested stretches. Named scene/character identity requires creator review.','',
        '| Group | Query | Model-matched sample seconds | Samples | Maximum grounding | Review status |',
        '| --- | --- | ---: | ---: | ---: | --- |']
    stats={};hard=[];no_match=[]
    for qid,q in qs.items():
        cs=[c for c in candidates if c['question_id']==qid and c['choice_pass']]
        by_video=collections.defaultdict(list)
        for c in cs:by_video[c['video_id']].append([c['start'],c['end']])
        seconds=sum(b-a for spans in by_video.values() for a,b in union(spans))
        windows=[r for r in all_rows if r['question_id']==qid]
        peak=max((p for r in windows for i,p in enumerate(r['probabilities']) if not r['black'][i]),default=0)
        state='Named scene/context review required' if cs and q['scenes'] else 'Literal match review required' if cs else 'No model-confirmed sample; inspect near misses'
        if not cs:no_match.append(qid)
        stats[qid]=dict(source_group=q['source_group'],query=q['query'],model_matched_seconds=seconds,samples=len(cs),maximum_grounding=peak,status=state,scene_confirmed=False)
        coverage.append(f"| {q['source_group']} | {q['query']} | {seconds:.1f} | {len(cs)} | {peak:.4f} | {state} |")
        rows=[r for r in representatives if r['question_id']==qid]
        files,omitted=sheets(rows,videos,target,qid,q['source_group']+' | '+q['query'])
        is_hard=bool(re.search('tank|rhino|helicopter|armory',q['query'],re.I))
        if is_hard:hard.append(dict(question_id=qid,**stats[qid],displayed_choices=sum(bool(r.get('choice')) for r in rows),displayed_without_choice=sum(not r.get('choice') for r in rows)))
        doc += [f'<details class="query" data-hard="{str(is_hard).lower()}"><summary>{html.escape(q["source_group"]+" — "+q["query"])}{(" — HARD NEED" if is_hard else "")}</summary>',
            '<p>Beats: '+html.escape(', '.join(q['beat_ids']))+'</p>',
            '<p>Named context: '+html.escape('; '.join(q['scenes']) or 'No named scene required')+'</p>',
            f'<p>Model-matched sampled supply: {seconds:.1f} s. Maximum grounding: {peak:.4f}. {html.escape(state)}.</p>',
            source_links(rows)]
        doc += [f'<img src="{html.escape(file)}" loading="lazy" alt="Representative scores and choice results">' for file in files]
        if omitted:doc += [f'<p>{omitted} black or unavailable thumbnails were omitted.</p>']
        doc += ['</details>']
    coverage += ['', '## Miss audit','',f"{len(audit['sources'])} long sources, three 30-second stretches each at 2 fps, independent of coarse retention. Only new video/question pairs were submitted. Prior cached-query audit results remain saved in the earlier Stage 3 report.",'',
        '| Video | Query | Start s | End s | Coarse-dropped s | Choice probability |','| --- | --- | ---: | ---: | ---: | ---: |']
    for c in audit['dropped_matches']:
        coverage.append(f"| {c['video_id']} | {qs[c['question_id']]['query']} | {c['start']:.3f} | {c['end']:.3f} | {c['coarse_dropped_seconds']:.3f} | {c['confirmation']:.4f} |")
    if not audit['dropped_matches']:coverage.append('| — | No sampled model-confirmed miss | — | — | — | — |')
    coverage+=['','## Hard-need choices','','| Group | Query | Displayed choice results | Cells without a covering choice |','| --- | --- | ---: | ---: |']
    for h in hard:coverage.append(f"| {h['source_group']} | {h['query']} | {h['displayed_choices']} | {h['displayed_without_choice']} |")
    coverage+=['','Blocked video: `tJbzMqJGH4k` — age-gated; replacement needed. Manual GTA 6 six-slot HUD remains outside automatic queries.','',
        'Stopped at the specific-query review gate. No assignment, new cuts/links, FilmCraft project or Stage 5 work was performed.']
    doc += ['<script>document.getElementById("find").addEventListener("input",e=>{const q=e.target.value.toLowerCase();for(const d of document.querySelectorAll(".query"))d.hidden=!d.textContent.toLowerCase().includes(q);});</script></html>']
    if audit['dropped_matches']:
        files,_=sheets(audit['dropped_matches'],videos,target,'miss-audit','Independent 2 fps audit: sampled matches dropped by coarse retention')
        doc[-1:-1]=['<h2>Miss-audit examples</h2>']+[f'<img src="{html.escape(file)}" loading="lazy" alt="Miss-audit scores and choices">' for file in files]
    (target/'review.html').write_text('\n'.join(doc),encoding='utf8')
    (folder/'coverage.md').write_text('\n'.join(coverage)+'\n',encoding='utf8')
    save_json(folder/'coverage.json',dict(questions=stats,no_confirmed_sample=no_match,hard_needs=hard,miss_audit=audit,
        general_pools_ready=10,beats_unchanged=True,assignment_started=False,stage5=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    render(p.parse_args().project.resolve())
