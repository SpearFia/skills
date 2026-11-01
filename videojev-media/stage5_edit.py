# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fill a gap or swap a shot in a saved review, always saving a separate file."""
import collections
import math
import time
from pathlib import Path

from filmcraft_rpc import FilmCraft
from jev import SOURCE_GROUPS
from script_assignment import Assignment
from script_first import approve,key,questions,read,sha
from script_queries import ScriptQueries,candidate_spans,spaced_examples
from stage3_sources import pool,save_json
from stage4_assign import FPS,cut_masters
from stage4_build import TICKS,ticks


def seconds(value):
    fields=value.split(':')
    if len(fields)>3:raise ValueError('Expected seconds, mm:ss or hh:mm:ss')
    values=[float(x) for x in fields]
    if any(not math.isfinite(x) or x<0 for x in values) or any(x>=60 for x in values[1:]):raise ValueError('Invalid timestamp')
    return sum(x*60**i for i,x in enumerate(reversed(values)))


def load_review(project,review):
    approve(project);review=review.resolve()
    if not review.is_relative_to(project.resolve()) or review.suffix!='.fcproj':raise ValueError('Use a saved review inside the demo project')
    data=read(review)
    if data.get('format')!='filmcraft.project':raise ValueError('Expected a FilmCraft project')
    sequences=[v['kind']['Sequence'] for v in data['project']['items'].values() if 'Sequence' in v['kind']]
    if len(sequences)!=1:raise ValueError('The demo must contain one sequence')
    return data,sequences[0]


def footage_tracks(project,sequence):
    ids=set(read(project/'media/jev/script-first/stage4/stage4-build.json')['tracks'].values())
    tracks=[t for t in sequence['video_tracks'] if t['id'] in ids]
    if not tracks:raise ValueError('Cannot identify the demo footage tracks')
    return tracks


def visible(tracks):
    clips=[(rank,c) for rank,t in enumerate(tracks) if t['enabled'] for c in t['items'] if c['enabled']]
    bounds=sorted({n for rank,c in clips for n in [c['start'],c['start']+c['duration']]})
    spans=[]
    for a,b in zip(bounds,bounds[1:]):
        covering=[(rank,c) for rank,c in clips if c['start']<=a and c['start']+c['duration']>=b]
        if not covering:continue
        c=max(covering,key=lambda r:r[0])[1]
        if spans and spans[-1][2]['id']==c['id'] and spans[-1][1]==a:spans[-1]=(spans[-1][0],b,c)
        else:spans.append((a,b,c))
    return spans


def master_map(project):
    folders=[project/'media/jev/script-first/stage4']+list((project/'media/jev/script-first/stage5/edits').glob('*'))
    return {str((project/m['file']).resolve()).casefold():m for folder in folders if (folder/'masters.json').exists() for m in read(folder/'masters.json')}


def source_spans(project,data,tracks):
    masters=master_map(project);items=data['project']['items'];spans=[]
    for a,b,c in visible(tracks):
        item=items[str(c['item'])];file=item['kind'].get('Media',{}).get('media',{}).get('File',{}).get('path')
        if not file:continue
        master=masters.get(str(Path(file).resolve()).casefold())
        if master is None:continue
        if c['reverse'] or c['speed']!=1:raise ValueError('Speed changes need explicit source-time mapping before edits')
        start=master['start']+(c['source_in']+a-c['start'])/TICKS
        spans.append(dict(video_id=master['video_id'],start=start,end=start+(b-a)/TICKS,timeline=a/TICKS,end_time=b/TICKS,clip=c['id']))
    return spans


def allocator(project,review,status=lambda text:None):
    data,seq=load_review(project,review);a=Assignment(project,status);a.quality_sources();a.hash_sources()
    tracks=footage_tracks(project,seq)
    groups={v['video_id']:g for g,p in a.pools.items() for v in p['videos']}
    for c in source_spans(project,data,tracks):
        vid=c['video_id'];a.used[vid].append([c['start']-1/30,c['end']+1/30]);a.placements[vid].append(round(c['timeline']*FPS))
        if vid in groups:
            a.share[groups[vid],vid]+=c['end']-c['start'];a.pool_used[groups[vid]]+=c['end']-c['start']
        for h in a.sample_hashes(vid,c['start'],c['end']):a.frame_index.add(h,str(c['clip']))
    return a,data,seq


def resolve_need(a,need):
    if need in a.pools:return dict(kind='general',question_id=None,groups=[need])
    if need in a.qs:qid=need
    else:
        ids={key(v['source_group'],v['query']) for v in a.document['visual_catalog'] if v.get('query') and
            (v.get('id')==need or v.get('saved_score_reference',{}).get('cache_need_id')==need)}
        if len(ids)!=1:raise ValueError('Use an approved question ID, visual ID, unambiguous saved need ID, or film/game group')
        qid=ids.pop()
    return dict(kind='specific',question_id=qid,groups=[a.qs[qid]['source_group']])


def choose_exact(a,slot):
    for _ in range(80):
        choices=[c for c in a.proposal(slot) if c['frames']==slot['duration_frames']]
        if not choices:return None
        for c in choices:
            if not a.duplicate(c['video_id'],c['start'],c['end']):return c
            a.rejected[c['video_id']].append([c['start'],c['end']])
        if slot['kind']=='specific':return None
    return None


class NewQuery(ScriptQueries):
    def __init__(self,a,group,query,status):
        self.project=a.project;self.root=a.root;self.qid=key(group,query);self.qs={self.qid:dict(id=self.qid,source_group=group,query=query)}
        self.folder=self.root/'stage5/queries'/self.qid;self.folder.mkdir(parents=True,exist_ok=True)
        self.cache=pool.cache_dir(a.project)/'jev-stage5'/self.qid;self.tasks=self.cache/'tasks';self.tasks.mkdir(parents=True,exist_ok=True)
        self.videos={v['video_id']:a.videos[v['video_id']] for v in a.pools[group]['videos']}
        self.allowed={(v,self.qid) for v in self.videos};self.excluded=a.excluded;self.worker=None;self.last_sample=None;self.status=status
        self.config=read(Path(__file__).with_name('config.json'));self.settings=self.config['index'];self.state={}
        self.windows=read(self.folder/'score-windows.json') if (self.folder/'score-windows.json').exists() else []
        self.candidates=read(self.folder/'candidates.json') if (self.folder/'candidates.json').exists() else []
        self.lookup=read(self.folder/'prediction-cache.json') if (self.folder/'prediction-cache.json').exists() else {}
        self.timings=read(self.folder/'timings.json') if (self.folder/'timings.json').exists() else []
        save_json(self.folder/'query.json',dict(group=group,query=query,context=32768,source_ids=sorted(self.videos)))

    def apply(self,a,slot):
        qid=self.qid;a.qs[qid]=self.qs[qid]
        def update():
            a.by_query[qid]=[c for c in self.candidates if c['choice_pass']]
            for vid in self.videos:a.cells[qid,vid]=[]
            for r in self.windows:
                for i,p in enumerate(r['probabilities']):
                    if not r['black'][i]:
                        lo,hi=r['bounds'][i];a.cells[qid,r['video_id']].append((r['start']+lo,r['start']+hi,p,r['fps']))
        update()
        if choose_exact(a,slot):return
        windows=[]
        for vid,v in self.videos.items():
            duration=v['probe']['duration']
            for start in range(0,math.ceil(duration),120):
                end=min(duration,start+120)
                if not any(y-x>=slot['duration_frames']/FPS for x,y in a.free_ranges(vid,start,end)):continue
                priority=max((p for (q,video),cells in a.cells.items() if video==vid and q!=qid for lo,hi,p,fps in cells if lo<end and hi>start),default=0)
                windows.append((-priority,vid,start,end))
        try:
            for _,vid,start,end in sorted(windows):
                rows=self.score(self.videos[vid],dict(start=start,end=end,needs=[qid]),3)
                for span in spaced_examples(candidate_spans(rows,self.excluded[vid])):
                    self.confirm(self.videos[vid],qid,span,'stage5-new-query');update()
                    if choose_exact(a,slot):return
        finally:
            if self.worker:
                (self.tasks/'stop').touch();self.worker.wait(timeout=60);self.worker=None


def slot_at(project,seq,mode,at):
    tracks=footage_tracks(project,seq);spans=visible(tracks);fields=at.split('-')
    if mode=='fill':
        if len(fields)!=2:raise ValueError('fill needs --at START-END')
        a,b=[round(seconds(s)*FPS) for s in fields]
        if b<=a:raise ValueError('End must be after start')
        if any(lo<ticks(b) and hi>ticks(a) for lo,hi,c in spans):raise ValueError('fill overlaps existing footage; use swap')
        removed=None
    else:
        if len(fields)!=1:raise ValueError('swap needs one timestamp')
        t=round(seconds(at)*TICKS);matches=[c for lo,hi,c in spans if lo<=t<hi]
        if not matches:raise ValueError('No visible footage at swap time; use fill')
        removed=matches[0];a=round(removed['start']/TICKS*FPS);b=a+round(removed['duration']/TICKS*FPS)
    return dict(id='stage5-'+str(time.time_ns()),start_frame=a,duration_frames=b-a,top=None,alternates=[]),removed


def edit(project,review,mode,at,need=None,query=None,group=None,status=lambda text:None,prepared=None):
    if mode not in {'fill','swap'}:raise ValueError('Expected fill or swap')
    if bool(need)==bool(query):raise ValueError('Choose exactly one of --need and --query')
    if query is not None and not query.strip():raise ValueError('Query cannot be empty')
    if query and group not in SOURCE_GROUPS:raise ValueError('New queries need --group')
    before=sha(review);a,data,seq=prepared or allocator(project,review,status)
    slot,removed=slot_at(project,seq,mode,at)
    if need:slot.update(resolve_need(a,need))
    else:
        qid=key(group,query);slot.update(kind='specific',question_id=qid,groups=[group])
        if qid not in a.qs:NewQuery(a,group,query,status).apply(a,slot)
    c=choose_exact(a,slot)
    if not c:return dict(status='unfilled',reason='No unused confirmed matching range of sufficient duration',mode=mode,at=at,input=str(review))
    slot['top']=c;folder=a.root/'stage5/edits'/slot['id'];folder.mkdir(parents=True)
    cut_masters(project,dict(slots=[slot]),a.videos,folder)
    tracks=read(a.root/'stage4/stage4-build.json')['tracks'];target=project/'sync'/('review-'+slot['id']+'.fcproj')
    if target.exists():raise FileExistsError(target)
    with FilmCraft() as f:
        f.command('file.open',path=str(review));snapshot=f.tool('sequence_inspect',{})
        if removed:f.command('edit.clear',clips=[removed['id']])
        imported=f.tool('media_import',dict(paths=[str(project/c['file'])]))
        if imported.get('errors') or len(imported['items'])!=1:raise RuntimeError('Master import failed')
        placed=f.command('timeline.place',item=imported['items'][0],track=tracks['top'],frame=slot['start_frame'],sourceIn=round(c['source_in']*TICKS),duration=ticks(slot['duration_frames']),audio=False)
        if len(placed['clips'])!=1:raise RuntimeError('Placement failed')
        clip=placed['clips'][0];f.command('clip.rename',clip=clip,name=f"Stage 5 {mode} {c['video_id']}")
        f.command('timeline.select',clips=[clip],add=False,toggle=False);f.command('clip.scaleToFrameSize');f.command('edit.deselectAll')
        after=f.tool('sequence_inspect',{});native=next(c for t in after['video'] for c in t['items'] if c['clip']==clip)
        assert (native['startFrame'],native['durationFrames'])==(slot['start_frame'],slot['duration_frames'])
        assert abs(native['sourceIn']/TICKS-slot['top']['source_in'])<=1/FPS+.000001
        assert after['audio']==snapshot['audio'],'An edit changed audio'
        other=lambda s:[c for t in s['video'] for c in t['items'] if c['clip'] not in {clip,removed['id'] if removed else None}]
        assert other(after)==other(snapshot),'An edit changed another clip'
        f.command('file.saveAs',path=str(target))
    assert sha(review)==before,'Input review changed'
    outdata,outseq=load_review(project,target);spans=source_spans(project,outdata,footage_tracks(project,outseq))
    old=source_spans(project,data,footage_tracks(project,seq));added=next(s for s in spans if s['clip']==clip)
    assert not any(s['video_id']==added['video_id'] and s['start']<added['end']-1e-6 and s['end']>added['start']+1e-6 for s in old),'New clip repeats existing footage'
    overlap_count=lambda rows:sum(a['video_id']==b['video_id'] and a['start']<b['end']-1e-6 and a['end']>b['start']+1e-6 for i,a in enumerate(rows) for b in rows[i+1:])
    result=dict(status='saved',mode=mode,input=str(review),output=str(target),at=at,slot=slot,input_unchanged=True,
        audio_unchanged=True,other_clips_unchanged=True,added_clip_repeats=False,existing_source_overlaps=overlap_count(old),
        remaining_source_overlaps=overlap_count(spans),new_query=bool(query and key(group,query) not in questions(a.document)))
    save_json(folder/'result.json',result)
    return result
