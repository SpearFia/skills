# SPDX-License-Identifier: MIT OR Apache-2.0
"""Compile approved sentence beats, preserve URLs, and reuse per-question scores."""
import argparse
import collections
import hashlib
import json
import math
import re
import shutil
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from jev import SOURCE_GROUPS,parse_checklist,validate_url
from stage3_index import subtract,union
from stage3_sources import pool,save_json


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def key(group,query):return hashlib.sha256((group+'\0'+' '.join(query.split()).casefold()).encode()).hexdigest()[:20]
def video_id(url):
    validate_url(url);p=urlsplit(url if '://' in url else 'https://'+url)
    return parse_qs(p.query)['v'][0] if p.path=='/watch' else p.path.rstrip('/').split('/')[-1]


def approve(project):
    """Only call after explicit creator approval; never overwrite the approved interpretation."""
    folder=project/'media/jev';draft=folder/'script-beats-draft.json';d=read(draft)
    original=Path(d['approved_script']).resolve().parent.parent
    if project.resolve()==original:raise ValueError('The approved original is read-only')
    if sha(d['approved_script'])!=d['approved_script_sha256'] or sha(project/'script/script.md')!=d['approved_script_sha256']:
        raise ValueError('Approved script changed; sentence beats must be reviewed again')
    target=folder/'script-first';receipt=target/'approval.json'
    if receipt.exists():
        r=read(receipt)
        if r['draft_sha256']!=sha(draft):raise ValueError('The beat draft changed after approval')
        if r['approved_sha256']!=sha(target/'beats.json'):raise ValueError('Approved beat interpretation was edited')
        return read(target/'beats.json')
    validate_beats(d)
    target.mkdir(exist_ok=True)
    shutil.copy2(draft,target/'beats.json')
    save_json(receipt,dict(creator='draft approved; continue',approved_at=datetime.now(timezone.utc).isoformat(),
        draft_sha256=sha(draft),approved_sha256=sha(target/'beats.json'),script_sha256=d['approved_script_sha256']))
    return d


def validate_beats(document):
    seen=set()
    for b in document['beats']:
        if b['id'] in seen or b['classification'] not in {'general','specific'}:raise ValueError('Invalid or duplicate beat')
        seen.add(b['id'])
        if not b['text'].strip() or b['line']<1 or not b['visuals']:raise ValueError('Beat has no script anchor or visual group')
        for v in b['visuals']:
            if v['source_group'] not in SOURCE_GROUPS:raise ValueError('Unknown source group')
            if b['classification']=='general' and v['query'] is not None:raise ValueError('General pools must have no query')
            if b['classification']=='specific' and not v.get('manual') and not v.get('query'):raise ValueError('Specific beat needs a query')
    if len(seen)!=document['counts']['sentences']:raise ValueError('Sentence coverage changed')


def questions(document):
    result={}
    for b in document['beats']:
        for v in b['visuals']:
            if b['classification']=='general' or v.get('manual'):continue
            qid=key(v['source_group'],v['query'])
            q=result.setdefault(qid,dict(id=qid,source_group=v['source_group'],query=v['query'],beat_ids=[],visual_ids=[],scenes=[]))
            for field,value in [('beat_ids',b['id']),('visual_ids',v['id']),('scenes',v.get('scene'))]:
                if value and value not in q[field]:q[field].append(value)
    return result


def checklist_sources(project,qs):
    folder=project/'media/jev/script-first';path=project/'production/media-checklist.md'
    known=list(read(project/'media/jev/sources.json'))
    names=known+['query-'+q for q in qs]+['archive-'+k for k in known]
    parsed=parse_checklist(path.read_text(encoding='utf8'),names)
    # Old optional URLs migrate only to an exactly equivalent specific question, never to a general pool.
    aliases=collections.defaultdict(set)
    for v in read(folder/'beats.json')['visual_catalog']:
        ref=v.get('saved_score_reference')
        if ref:aliases[ref['cache_need_id']].add(key(v['source_group'],v['query']))
    groups={g:parsed.get('group-'+g,[]) for g in SOURCE_GROUPS}
    optional={q:parsed.get('query-'+q,[]) for q in qs};archived={}
    for name in known:
        if name.startswith('group-'):continue
        urls=list(dict.fromkeys(parsed.get(name,[])+parsed.get('archive-'+name,[])))
        if not urls:continue
        if name in aliases:
            for q in aliases[name]:optional[q]=list(dict.fromkeys(optional[q]+urls))
        else:archived[name]=urls
    return dict(groups=groups,optional=optional,archived=archived)


def blockers(document,downloads):
    out={v['video_id']:dict(video_id=v['video_id'],reason='Age-gated',action='Paste a replacement; no bypass or retry') for v in document.get('source_blockers',[])}
    for v in downloads['videos']:
        if v['status']=='ready':continue
        out.setdefault(v['id'],dict(video_id=v['id'],reason=v['status'],action='Replace the URL or resolve the source externally'))
    return list(out.values())


def render_checklist(document,qs,sources,blocked):
    lines=['# VideoJev script-first checklist','','## Blocked videos — replacements needed','']
    lines += [f"- `{b['video_id']}`: **{b['reason']}**. {b['action']}." for b in blocked] or ['No blocked sources.']
    lines += ['', f"The creator approved the {document['counts']['sentences']} sentence beats in `jev-script-beats-draft.html`. This checklist uses that interpretation. Saved source results remain intact.",
        '', 'Each group supplies its full general pool without a question: all footage except text screens and black frames. Specific beats below use their approved short visual queries. General footage is spaced without repeats. A source belongs to the group box where its URL was pasted; no borrowing from another group.',
        '', 'Specific inserts are brief; the surrounding commentary uses general footage. No old cue duration or 3× narration quota is carried forward. The GTA 6 six-slot HUD remains manual. New VideoJev work stays at context 32,768; existing per-question scores are reused.', '']
    for group,label in SOURCE_GROUPS.items():
        lines += ['## group-'+group+': '+label,'','General pool: **no query**. All usable footage from these URLs; exclude black frames and text screens.']
        lines += [f"Specific questions for this group: {sum(q['source_group']==group for q in qs.values())}. Only uncached video/question pairs are eligible for new model work.",'']
        if group=='gta6':lines+=['Official promotional footage only. The six-slot HUD is handled by hand.','']
        lines += ['```text',*(sources['groups'][group] or ['Paste URLs here, one per line.']),'```','']
    lines += ['## Optional specific-query URLs','','These additions apply only to the question shown. They never enlarge the general pool. Named-scene identity still matters; a high retrieval score alone is not scene confirmation.','']
    for qid,q in qs.items():
        lines += [f"### query-{qid}: {SOURCE_GROUPS[q['source_group']]}",'',q['query'],'',
            'Beats: '+', '.join(q['beat_ids'])+'.','']
        if q['scenes']:lines+=['Named scene/context: '+'; '.join(q['scenes'])+'.','']
        lines+=['```text',*(sources['optional'][qid] or ['Paste optional URLs here.']),'```','']
    if sources['archived']:
        lines += ['## Preserved optional entries','','These old optional entries have no approved equivalent question. Their URLs remain saved here and are inactive.','']
        for name,urls in sources['archived'].items():lines += ['### archive-'+name+': inactive','','```text',*urls,'```','']
    return '\n'.join(lines)


def cached_scores(cache,windows,qs,allowed):
    """Read native question outputs, never the legacy max-across-variants summaries."""
    by_text=collections.defaultdict(list)
    for q in qs.values():by_text[' '.join(q['query'].split()).casefold()].append(q['id'])
    origins={}
    for w in windows:
        k=(w['window_id'],w['video_id'],w['start'],w['end'],w['fps'])
        origins.setdefault(k,w)
    rows=[];seen=set();unavailable=0
    for (wid,vid,a,b,fps),w in origins.items():
        for tasks in ['tasks-v2','tasks']:
            path=cache/tasks/(wid+'.result.json')
            if not path.exists():continue
            result=read(path)
            if result.get('status')!='complete' or result.get('context')!=32768:continue
            native=result['record'];bounds=[[lo,min(hi,b-a)] for lo,hi in native['score_bounds']]
            for answer in result['queries']:
                question=answer['question']
                if question['task']!='grounding':continue
                for qid in by_text.get(' '.join(question['query'].split()).casefold(),[]):
                    ident=(qid,vid,wid,a,b,fps)
                    if vid not in allowed[qid] or ident in seen:continue
                    probabilities=answer['output']['probabilities']
                    if len(probabilities)!=len(bounds) or any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities):
                        raise ValueError('Invalid native score vector: '+str(path))
                    rows.append(dict(question_id=qid,video_id=vid,start=a,end=b,fps=fps,bounds=bounds,
                        probabilities=probabilities,frames=native['frames'],black=w['black'],
                        provenance=dict(result=str(path),native_question_id=question['id'],native_query=question['query']),
                        scene_confirmed=False))
                    seen.add(ident)
            break
        else:unavailable+=1
    return rows,unavailable


def general_pools(project,sources,videos,blocked):
    cache=pool.cache_dir(project)/'jev-index';folder=project/'media/jev/script-first'
    pools=[]
    for group,urls in sources['groups'].items():
        entries=[]
        for vid in dict.fromkeys(video_id(url) for url in urls):
            if vid in blocked:continue
            video=videos.get(vid)
            if not video or video['status']!='ready':
                entries.append(dict(video_id=vid,status='not_downloaded'));continue
            black_path=cache/(vid+'.black.json');text_path=folder/'text-scans'/(vid+'.json')
            black=read(black_path)['ranges'] if black_path.exists() else None
            text=read(text_path) if text_path.exists() else None
            if text and (text['source_size']!=Path(video['path']).stat().st_size or text['crop']!=video.get('crop')):
                raise ValueError('Text scan is stale: '+vid)
            ready=black is not None and text is not None and text.get('status')=='complete'
            spans=subtract(0,video['probe']['duration'],black+text['ranges']) if ready else None
            entries.append(dict(video_id=vid,path=video['path'],duration=video['probe']['duration'],crop=video.get('crop'),
                status='ready' if ready else 'quality_scan_pending',black_ranges=black,text_ranges=text['ranges'] if text else None,
                usable_ranges=spans))
        pools.append(dict(source_group=group,query=None,status='ready' if entries and all(v['status']=='ready' for v in entries) else 'pending',
            selection='All usable ranges; spacing and no-repeat apply when selecting, not a positive-query filter',videos=entries))
    return pools


def choose_general(general,duration,used,last_used,timeline_seconds):
    """Consume globally unique source ranges; divide the largest free stretches for spacing."""
    if general['query'] is not None or general['status']!='ready':raise ValueError('General pool quality scans must finish first')
    choices=[]
    for video in general['videos']:
        vid=video['video_id']
        for lo,hi in video['usable_ranges']:
            for a,b in subtract(lo,hi,used.get(vid,[])):
                if b-a+1e-6<duration:continue
                start=(a+b-duration)/2
                recent=timeline_seconds-last_used.get(vid,-1e9)<60
                spent=sum(y-x for x,y in union(used.get(vid,[])))
                choices.append((recent,spent/max(.001,video['duration']),-(b-a),vid,start))
    if not choices:return None
    _,_,_,vid,start=min(choices)
    used.setdefault(vid,[]).append([start,start+duration]);last_used[vid]=timeline_seconds
    return dict(video_id=vid,start=start,end=start+duration,source_group=general['source_group'],query=None)


def prepare(project):
    d=approve(project);folder=project/'media/jev/script-first';qs=questions(d)
    checklist=project/'production/media-checklist.md'
    if not (folder/'checklist-before.md').exists():shutil.copy2(checklist,folder/'checklist-before.md')
    sources=checklist_sources(project,qs);downloads=read(project/'media/jev/download-report.json')
    videos={v['id']:v for v in downloads['videos']};blocked=blockers(d,downloads);blocked_ids={v['video_id'] for v in blocked}
    allowed={qid:set(video_id(url) for url in sources['groups'][q['source_group']]+sources['optional'][qid]) for qid,q in qs.items()}
    cache=pool.cache_dir(project)/'jev-index'
    rows,unavailable=cached_scores(cache,read(project/'media/jev/score-windows.json'),qs,allowed)
    hits=collections.Counter((r['question_id'],r['video_id']) for r in rows)
    coverage=collections.defaultdict(list)
    for r in rows:coverage[r['question_id'],r['video_id']].append([r['start'],r['end']])
    jobs=[]
    for qid,q in qs.items():
        for vid in sorted(allowed[qid]):
            if vid in blocked_ids:state='blocked'
            elif vid not in videos or videos[vid]['status']!='ready':state='download_pending'
            else:state='reuse_saved_scores' if hits[qid,vid] else 'new_query'
            saved_seconds=sum(b-a for a,b in union(coverage[qid,vid]))
            duration=videos.get(vid,{}).get('probe',{}).get('duration')
            jobs.append(dict(question_id=qid,video_id=vid,status=state,saved_windows=hits[qid,vid],saved_span_seconds=saved_seconds,
                untested_seconds=max(0,duration-saved_seconds) if duration is not None else None))
    pools=general_pools(project,sources,videos,blocked_ids)
    quality=read(folder/'quality-run.json') if (folder/'quality-run.json').exists() else dict(status='not_started')
    save_json(folder/'sources.json',sources);save_json(folder/'questions.json',list(qs.values()))
    save_json(folder/'score-reuse.json',dict(rows=rows,unavailable_native_windows=unavailable,
        policy='Native per-question retrieval scores only; no inherited scene confirmation or variant maxima'))
    save_json(folder/'general-pools.json',pools)
    save_json(folder/'job-plan.json',dict(status='prepared_not_running',context=32768,queries=jobs,
        model_jobs=[j for j in jobs if j['status']=='new_query'],blocked_videos=blocked,
        llm_after_beats=False,legacy_plan_allowed=False,stage5=False))
    checklist.write_text(render_checklist(d,qs,sources,blocked),encoding='utf8')
    summary=dict(status='prepared_not_running',beats=d['counts']['sentences'],questions=len(qs),
        general_pools=len(pools),query_pairs=dict(collections.Counter(j['status'] for j in jobs)),
        saved_native_windows=len(rows),native_windows_unavailable=unavailable,
        pools_pending_quality=sum(p['status']!='ready' for p in pools),blocked_videos=blocked,
        pasted_url_entries=sum(len(urls) for section in sources.values() for urls in section.values()),
        partial_cached_pairs=sum(j['status']=='reuse_saved_scores' and j['untested_seconds']>.5 for j in jobs),quality_run=quality)
    if quality['status']=='running':summary['status']='general_pool_scans_running'
    elif quality['status']=='complete':summary['status']='general_pools_ready_queries_not_run' if not summary['pools_pending_quality'] else 'waiting_for_source_quality'
    elif quality['status']=='failed':summary['status']='general_pool_scans_failed'
    save_json(folder/'summary.json',summary)
    lines=['# Approved beat implementation — short summary','',
        f"Status: {summary['status']}. {summary['beats']} beats; {len(qs)} deduplicated visual questions; 10 query-free general pools.",'',
        f"Reused native score windows: {len(rows)}. Video/question pairs: "+str(summary['query_pairs'])+'.','',
        f"Cached pairs with untested stretches: {summary['partial_cached_pairs']}. Untested stretches are not evidence that a shot is absent.",'',
        f"General pools awaiting text/black quality scans: {summary['pools_pending_quality']}. Quality scan state: {quality['status']}. No model query or timeline build was started.",'',
        'Blocked videos: '+', '.join('`'+b['video_id']+'` ('+b['reason']+')' for b in blocked)+'. Age gates are not bypassed.','',
        'The current checklist keeps group URLs and migrates equivalent optional URLs. Unmapped optional URLs remain archived in the checklist. Existing needs, scores, completed-video results, assignments and FilmCraft reviews are preserved.','',
        'The old cue-based index/assign/build commands are disabled for this project. New general pools require completed deterministic quality scans before selection. Stage 5 remains stopped.']
    if quality.get('error'):lines+=['','Quality scan error: '+quality['error'][:1000]]
    lines+=['','## General pool supply','','| Group | Sources | Quality complete | Usable seconds |','| --- | ---: | ---: | ---: |']
    for p in pools:
        ready=[v for v in p['videos'] if v['status']=='ready']
        seconds=sum(b-a for v in ready for a,b in v['usable_ranges'])
        amount=f'{seconds:.1f}' if p['status']=='ready' else 'pending'
        lines.append(f"| {p['source_group']} | {len(p['videos'])} | {len(ready)} | {amount} |")
    (project/'production/jev-script-first-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    prepare(p.parse_args().project.resolve())
