# SPDX-License-Identifier: MIT OR Apache-2.0
"""Word-time the approved sentences and assign literal inserts plus query-free footage."""
import bisect
import collections
import difflib
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from script_first import approve,key,questions,read
from script_queries import saved_choices
from stage3_index import subtract,union
from stage3_sources import pool,save_json
from stage4_assign import FPS,HANDLE,FrameIndex,fingerprints,norm,spoken,assert_no_overlap


def beat_times(project,document):
    lines=(project/'script/script.md').read_text(encoding='utf-8-sig').splitlines()
    heard=read(project/'media/vo-words.json')
    links=sorted((l for l in pool.links(project) if l.get('role')=='voiceover'),key=lambda l:l['line'])
    plan=read(max((project/'sync/plans').glob('*.json'),key=lambda p:p.stat().st_mtime))
    audio={i['source']['path']:i for i in plan['items'] if i['kind']=='clip' and i['track']=='A1'}
    by_line=collections.defaultdict(list)
    for b in document['beats']:by_line[b['line']].append(b)
    result={}
    for index,link in enumerate(links):
        end=links[index+1]['line'] if index+1<len(links) else len(lines)
        words=[];positions={}
        for line in range(link['line'],end):
            if lines[line].startswith('VO:'):
                tokens=spoken(lines[line]).split();positions[line+1]=(len(words),tokens);words+=tokens
        path=link['media']['path'];record=heard[path]['words'];item=audio[path]
        matcher=difflib.SequenceMatcher(None,[norm(w) for w in words],[norm(w[0]) for w in record],autojunk=False)
        known={a+i:record[b+i][1] for a,b,n in matcher.get_matching_blocks() for i in range(n)}
        starts=[];duration=item['duration_frames']/FPS
        for i in range(len(words)):
            if i in known:starts.append(known[i]);continue
            before=max((j for j in known if j<i),default=-1);after=min((j for j in known if j>i),default=len(words))
            lo=known.get(before,0);hi=known.get(after,duration)
            starts.append(lo+(hi-lo)*(i-before)/(after-before))
        starts.append(duration)
        if any(b<a for a,b in zip(starts,starts[1:])):raise ValueError('Nonmonotonic narration timing')
        for line,(offset,tokens) in positions.items():
            beats=sorted(by_line[line],key=lambda b:b['sentence'])
            if ' '.join(b['text'] for b in beats)!=spoken(lines[line-1]):raise ValueError('Sentence anchors do not cover the approved line')
            used=0
            for b in beats:
                count=len(b['text'].split())
                a=item['start_frame']+round(starts[offset+used]*FPS);used+=count
                z=item['start_frame']+round(starts[offset+used]*FPS)
                result[b['id']]=dict(start_frame=a,end_frame=z,vo_path=path,alignment_fraction=len(known)/len(words))
    if set(result)!={b['id'] for b in document['beats']}:raise ValueError('Not every approved sentence was word-timed')
    return result


def make_slots(document,timing):
    proof=[];general=[]
    for b in document['beats']:
        t=timing[b['id']];a=t['start_frame'];z=t['end_frame']
        if z<=a:continue
        groups=list(dict.fromkeys(v['source_group'] for v in b['visuals']))
        common=dict(beat_ids=[b['id']],vo_path=t['vo_path'],line=b['line']-1,quote=b['text'],groups=groups)
        if b['classification']=='specific':
            visuals=b['visuals'][:max(1,(z-a)//30)]
            budget=min(z-a,max(90,len(visuals)*45))
            for i,v in enumerate(visuals):
                lo=a+budget*i//len(visuals);hi=a+budget*(i+1)//len(visuals)
                proof.append(dict(common,id='proof-'+b['id']+'-'+str(i),kind='manual' if v.get('manual') else 'specific',
                    question_id=None if v.get('manual') else key(v['source_group'],v['query']),groups=[v['source_group']],start_frame=lo,duration_frames=hi-lo,top=None,alternates=[]))
            a+=budget
        if a<z:general.append(dict(common,start_frame=a,end_frame=z))
    return proof,general


def general_slots(spans):
    merged=[]
    for s in sorted(spans,key=lambda s:s['start_frame']):
        if merged and s['start_frame']==merged[-1]['end_frame'] and s['groups']==merged[-1]['groups'] and s['vo_path']==merged[-1]['vo_path']:
            merged[-1]['end_frame']=s['end_frame'];merged[-1]['beat_ids']+=s['beat_ids']
        else:merged.append(dict(s,beat_ids=list(s['beat_ids'])))
    slots=[]
    for s in merged:
        count=max(1,math.ceil((s['end_frame']-s['start_frame'])/120))
        for i in range(count):
            a=s['start_frame']+(s['end_frame']-s['start_frame'])*i//count
            b=s['start_frame']+(s['end_frame']-s['start_frame'])*(i+1)//count
            slots.append(dict(s,id='general-'+str(len(slots)),kind='general',question_id=None,start_frame=a,duration_frames=b-a,top=None,alternates=[]))
    return slots


class Assignment:
    def __init__(self,project,status=lambda phase:None):
        self.project=project;self.document=approve(project);self.root=project/'media/jev/script-first';self.folder=self.root/'stage4';self.folder.mkdir(exist_ok=True)
        if read(self.root/'query-run.json')['status'] not in {'specific_query_gate_ready','specific_query_gate_ready_with_failures'}:raise ValueError('Specific-query gate is not ready')
        self.qs=questions(self.document);self.status=status
        self.videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
        self.pools={p['source_group']:p for p in read(self.root/'general-pools.json')}
        if any(p['status']!='ready' for p in self.pools.values()):raise ValueError('General pools are not ready')
        self.quality={v['video_id']:v['usable_ranges'] for p in self.pools.values() for v in p['videos']}
        self.excluded={v['video_id']:union(v['black_ranges']+v['text_ranges']) for p in self.pools.values() for v in p['videos']}
        self.plan=read(self.root/'job-plan.json');self.allowed={(j['video_id'],j['question_id']) for j in self.plan['queries'] if j['status'] in {'reuse_saved_scores','new_query'}}
        pairs={(j['video_id'],j['question_id']) for j in self.plan['queries'] if j['status']=='reuse_saved_scores'}
        cached=saved_choices(read(project/'media/jev/candidates.json'),self.document,self.qs,pairs,self.excluded)
        self.candidates=[c for c in cached+read(self.root/'query-results/candidates.json') if c['choice_pass'] and (c['video_id'],c['question_id']) in self.allowed]
        self.by_query=collections.defaultdict(list)
        for c in self.candidates:self.by_query[c['question_id']].append(c)
        self.cells=collections.defaultdict(list)
        for r in read(self.root/'score-reuse.json')['rows']+read(self.root/'query-results/score-windows.json'):
            for i,p in enumerate(r['probabilities']):
                if not r['black'][i]:
                    a,b=r['bounds'][i];self.cells[r['question_id'],r['video_id']].append((r['start']+a,r['start']+b,p,r['fps']))
        self.used=collections.defaultdict(list);self.rejected=collections.defaultdict(list);self.placements=collections.defaultdict(list)
        self.share=collections.Counter();self.pool_used=collections.Counter();self.frames={};self.times={};self.frame_index=FrameIndex()
        self.duplicates=0;self.hash_cache=pool.cache_dir(project)/'jev-stage4/hashes';self.hash_cache.mkdir(parents=True,exist_ok=True)

    def hash_sources(self):
        ids={v['video_id'] for p in self.pools.values() for v in p['videos']}|{c['video_id'] for c in self.candidates}
        def load(vid):return vid,fingerprints(self.videos[vid],self.hash_cache)
        with ThreadPoolExecutor(max_workers=4) as executor:
            for vid,rows in executor.map(load,sorted(ids)):
                self.frames[vid]=rows;self.times[vid]=[r['time'] for r in rows];self.status('Fingerprint source '+vid)

    def quality_sources(self):
        from script_text_screens import WindowsOcr,black_scan,scan_video
        missing=sorted({c['video_id'] for c in self.candidates}-set(self.quality))
        if not missing:return
        with WindowsOcr() as ocr:
            for vid in missing:
                self.status('Local text/black filter '+vid)
                v=self.videos[vid];target=self.root/'text-scans'/(vid+'.json')
                black=black_scan(v,pool.cache_dir(self.project)/'jev-index')
                text=read(target) if target.exists() else scan_video(v,black,ocr,target)
                if text['status']!='complete' or text['source_size']!=Path(v['path']).stat().st_size or text['crop']!=v.get('crop'):
                    raise ValueError('Stale text-screen scan: '+vid)
                self.excluded[vid]=union(black+text['ranges'])
                self.quality[vid]=subtract(0,v['probe']['duration'],self.excluded[vid])

    def sample_hashes(self,vid,a,b):
        return self.frames[vid][bisect.bisect_left(self.times[vid],a):bisect.bisect_left(self.times[vid],b)]

    def duplicate(self,vid,a,b):
        hits=collections.defaultdict(list)
        for i,h in enumerate(self.sample_hashes(vid,a,b)):
            for distance,old,source in self.frame_index.matches(h):
                if distance<=16 and max(abs(x-y) for x,y in zip(h['color'],old['color']))<=16:hits[source].append((i,old['time']-h['time']))
        return any(len({i for i,offset in rows if abs(offset-target)<.15})>=3 for rows in hits.values() for _,target in rows)

    def raw_score(self,qid,vid,a,b):
        cells=[c for c in self.cells[qid,vid] if c[0]<b and c[1]>a]
        if not cells:return .5
        rate=max(c[3] for c in cells);cells=[c for c in cells if c[3]==rate]
        weights=[max(0,min(b,y)-max(a,x)) for x,y,p,fps in cells]
        return sum(c[2]*w for c,w in zip(cells,weights))/max(1e-9,sum(weights))

    def free_ranges(self,vid,a,b,extra=None):
        occupied=self.used[vid]+self.rejected[vid]+(extra or {}).get(vid,[])
        for lo,hi in self.quality[vid]:
            lo=max(a,lo+HANDLE if lo>0 else lo);hi=min(b,hi-HANDLE if hi<self.videos[vid]['probe']['duration'] else hi)
            if hi>lo:yield from subtract(lo,hi,occupied)

    def proposal(self,slot,alternate=False):
        duration=slot['duration_frames']/FPS;extra=collections.defaultdict(list)
        for c in slot['alternates']:extra[c['video_id']].append([c['start'],c['end']])
        selected={c['video_id'] for c in ([slot['top']] if slot['top'] else [])+slot['alternates']}
        choices=[]
        if slot['kind']=='specific':
            qid=slot['question_id']
            for c in self.by_query[qid]:
                vid=c['video_id']
                if vid not in self.quality:continue
                for lo,hi in self.free_ranges(vid,c['start'],c['end'],extra):
                    frames=min(slot['duration_frames'],int((hi-lo+1e-7)*FPS))
                    if frames<min(30,slot['duration_frames']) or (alternate and frames!=slot['duration_frames']):continue
                    length=frames/FPS
                    peaks=sorted((x for x in self.cells[qid,vid] if x[0]<hi and x[1]>lo),key=lambda x:-x[2])[:6]
                    starts={lo,(lo+hi-length)/2,hi-length}|{max(lo,min(hi-length,(x+y-length)/2)) for x,y,p,fps in peaks}
                    for a in starts:
                        score=self.raw_score(qid,vid,a,a+length)*c['confirmation']
                        recent=any(abs(t-slot['start_frame'])<60*FPS for t in self.placements[vid])
                        choices.append(((alternate and vid in selected,recent,-score),dict(video_id=vid,start=a,end=a+length,score=score,
                            confirmation=c['confirmation'],candidate_id=c['id'],question_id=qid,source_group=self.qs[qid]['source_group'],frames=frames)))
        elif slot['kind']=='general':
            for group in slot['groups']:
                for v in self.pools[group]['videos']:
                    vid=v['video_id']
                    for lo,hi in self.free_ranges(vid,0,v['duration'],extra):
                        if hi-lo+1e-6<duration:continue
                        a=(lo+hi-duration)/2
                        recent=any(abs(t-slot['start_frame'])<60*FPS for t in self.placements[vid])
                        share=self.share[group,vid]/max(1,self.pool_used[group]);pool_share=self.pool_used[group]/max(1,sum(x['duration'] for x in self.pools[group]['videos']))
                        choices.append(((alternate and vid in selected,recent,pool_share,share>.25,share,-(hi-lo)),dict(video_id=vid,start=a,end=a+duration,score=None,
                            source_group=group,frames=slot['duration_frames'],question_id=None)))
        return [c for _,c in sorted(choices,key=lambda x:x[0])]

    def book(self,slot,c):
        slot['top']=c;vid=c['video_id'];margin=1/max(1,self.videos[vid]['probe']['fps'])
        self.used[vid].append([max(0,c['start']-margin),c['end']+margin]);self.placements[vid].append(slot['start_frame'])
        self.share[c['source_group'],vid]+=c['end']-c['start'];self.pool_used[c['source_group']]+=c['end']-c['start']
        for h in self.sample_hashes(vid,c['start'],c['end']):self.frame_index.add(h,slot['id'])

    def choose(self,slot,alternate=False):
        for _ in range(80):
            choices=self.proposal(slot,alternate)
            for c in choices:
                if not self.duplicate(c['video_id'],c['start'],c['end']):return c
                self.duplicates+=1;self.rejected[c['video_id']].append([c['start'],c['end']])
            if not choices or slot['kind']=='specific':return None
        return None

    def allocate(self):
        timing=beat_times(self.project,self.document);save_json(self.folder/'beat-times.json',timing)
        proof,general=make_slots(self.document,timing)
        demand=collections.Counter()
        for s in proof:
            if s['question_id']:demand[s['question_id']]+=s['duration_frames']/FPS
        supply={qid:sum(b-a for spans in self.source_supply(qid).values() for a,b in union(spans)) for qid in demand}
        for s in sorted(proof,key=lambda s:(s['kind']=='manual',supply.get(s['question_id'],0)/max(1,demand.get(s['question_id'],0)),s['start_frame'])):
            if s['kind']=='manual':s['unfilled_reason']='Handled by hand';continue
            c=self.choose(s)
            if c:
                if c['frames']<s['duration_frames']:
                    end=s['start_frame']+s['duration_frames'];s['duration_frames']=c['frames']
                    general.append(dict(s,start_frame=s['start_frame']+c['frames'],end_frame=end,groups=s['groups']))
                self.book(s,c)
            else:s['unfilled_reason']='No unused model-confirmed literal range'
        slots=proof+general_slots(general)
        for i,s in enumerate(sorted((s for s in slots if s['kind']=='general'),key=lambda s:s['start_frame'])):
            c=self.choose(s)
            if c:self.book(s,c)
            else:s['unfilled_reason']='No unused general footage with required handles'
            if i%50==0:self.status(f'Assign general slots {i}')
        for i,s in enumerate(slots):
            if not s['top']:continue
            for _ in range(2):
                c=self.choose(s,True)
                if c:s['alternates'].append(c)
                else:break
            if i%50==0:self.status(f'Choose alternates {i}')
        slots.sort(key=lambda s:s['start_frame']);assert_no_overlap(slots)
        if any(a['start_frame']+a['duration_frames']>b['start_frame'] for a,b in zip(slots,slots[1:])):raise AssertionError('Overlapping timeline slots')
        result=dict(fps=FPS,handles_seconds=HANDLE,slots=slots,original_project=str(Path(self.document['approved_script']).parent.parent),
            original_script_sha256=self.document['approved_script_sha256'],duplicate_candidates_rejected=self.duplicates,
            beat_count=len(timing),zero_duration_beats=[k for k,t in timing.items() if t['start_frame']==t['end_frame']])
        save_json(self.folder/'assignment.json',result)
        return result

    def source_supply(self,qid):
        grouped=collections.defaultdict(list)
        for c in self.by_query[qid]:grouped[c['video_id']].append([c['start'],c['end']])
        return grouped
