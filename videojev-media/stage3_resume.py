# SPDX-License-Identifier: MIT OR Apache-2.0
"""Quota-limited Stage 3 resume. The stopped run's completed videos are immutable."""
import argparse
import copy
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from stage3_index import Indexer, digest, merge_windows, runs, scope_status, subtract, union
from stage3_sources import command, save_json


class StopRequested(Exception):
    pass


def append(path, value):
    with path.open('a',encoding='utf-8') as output:
        output.write(json.dumps(value)+'\n')


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def seconds(spans):
    return sum(b-a for a,b in union(spans))


def spaced(a,b,pieces,gap=4):
    return all(b+gap<=p['start']+1e-6 or a>=p['end']+gap-1e-6 for p in pieces)


def freeze_check(path,duration):
    started=time.perf_counter()
    result=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-an',
        '-vf','freezedetect=n=-50dB:d=1','-f','null','-'],capture_output=True,text=True,timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    starts=[float(x) for x in re.findall(r'freeze_start:\s*([\d.]+)',result.stderr)]
    ends=[float(x) for x in re.findall(r'freeze_end:\s*([\d.]+)',result.stderr)]
    intervals=[[a,min(duration,ends[i] if i<len(ends) else duration)] for i,a in enumerate(starts)]
    longest=max((b-a for a,b in intervals),default=0)
    return dict(frozen=longest>=max(1.,.8*duration),intervals=intervals,seconds=time.perf_counter()-started,
        noise='-50dB',minimum_seconds=1.,rejection_fraction=.8)


def recover_legacy(index,videos):
    """Rebuild saved window metadata from committed score cells; never run the model."""
    legacy=index.cache/'tasks'
    windows,lookup=[],{}
    groups=index.db.execute('SELECT video_id,round,window_id,MIN(t0),MAX(t1) FROM scores GROUP BY video_id,round,window_id').fetchall()
    for video_id,number,key,a,b in groups:
        result_path=legacy/(key+'.result.json')
        request_path=legacy/(key+'.request.json')
        if video_id not in videos or not result_path.exists() or not request_path.exists():
            continue
        result=json.loads(result_path.read_text(encoding='utf-8'))
        if result.get('status')!='complete':
            continue
        record=result['record']
        b=min(b,videos[video_id]['probe']['duration'])
        request=json.loads(request_path.read_text())
        path=request['path']
        if path.startswith('/mnt/'):
            path=path[5].upper()+':/'+path[7:]
        sample=dict(path=path,start=a,end=b,video_id=video_id,fps=record['fps'])
        lookup.setdefault((video_id,round(a,6),round(b,6),record['fps']),[]).append((key,result,sample))
        black_path=index.cache/(video_id+'.black.json')
        black=json.loads(black_path.read_text())['ranges'] if black_path.exists() else []
        flags=[any(lo-1e-6<=a+min(2*i+j,record['frames']-1)/record['fps']<hi-1e-6
            for j in [0,1] for lo,hi in black) for i in range(len(record['score_bounds']))]
        bounds=[[lo,min(hi,b-a)] for lo,hi in record['score_bounds']]
        for need_id in index.needs:
            vectors=[q['output']['probabilities'] for q in result['queries'] if q['question']['task']=='grounding' and q['question']['id'].startswith(need_id+'-v')]
            if vectors:
                windows.append(dict(video_id=video_id,need_id=need_id,round=abs(number),window_id=key,start=a,end=b,
                    fps=record['fps'],probabilities=[max(values) for values in zip(*vectors)],bounds=bounds,black=flags,
                    frames=record['frames'],audit=number<0,query_mode='legacy',sampled_clip=sample))
    return windows,lookup


class BudgetIndexer(Indexer):
    def __init__(self,project):
        super().__init__(project)
        self.policy=json.loads((self.folder/'resume-policy.json').read_text())
        self.frozen=set(self.policy['completed_videos'])
        downloads=json.loads((self.folder/'download-report.json').read_text(encoding='utf-8'))
        self.downloads=downloads
        self.videos={v['id']:v for v in downloads['videos'] if v['status']=='ready'}
        self.tasks=self.cache/'tasks-v2'
        self.tasks.mkdir(exist_ok=True)
        self.events=self.folder/'resume-events'
        self.events.mkdir(exist_ok=True)
        legacy_candidates=json.loads((Path(self.policy['checkpoint'])/'candidates.json').read_text(encoding='utf-8'))
        self.candidates=[c for c in legacy_candidates if c['video_id'] in self.frozen]
        self.legacy_fingerprint=digest(self.candidates)
        legacy_windows,self.lookup=recover_legacy(self,self.videos)
        self.windows=[w for w in legacy_windows if w['video_id'] in self.frozen]
        save_json(self.folder/'legacy-score-windows.json',self.windows)
        for candidate in read_events(self.events/'candidates.jsonl'):
            if candidate['id'] not in {c['id'] for c in self.candidates}:
                self.candidates.append(candidate)
        for row in read_events(self.events/'windows.jsonl'):
            if self.row_key(row) not in {self.row_key(w) for w in self.windows}:
                self.windows.append(row)
        self.timings=read_events(self.events/'timings.jsonl')
        self.metrics=read_events(self.events/'metrics.jsonl')
        self.profiles=read_events(self.events/'videos.jsonl')
        self.sampled_windows={key:[] for key in self.videos}
        for row in self.windows:
            if row['round']==3 and row.get('sampled_clip'):
                self.sampled_windows[row['video_id']].append(row['sampled_clip'])
        self.query_mode='main'
        self.audit_plan=json.loads((self.folder/'miss-audit-plan.json').read_text())['sources']
        self.relaxed=set()
        self.phase='initial'
        cues={c['id']:c for c in self.inputs['cues']}
        self.targets={key:3*sum(cues[c]['seconds_estimate'] for c in n['cues']) for key,n in self.needs.items()}
        self.pools={}
        self.tested={c['id'] for c in self.candidates}
        self.state.update(completed_videos=list(self.policy['completed_videos']),frozen_completed_videos=list(self.policy['completed_videos']),
            initial_pass_videos=[p['video_id'] for p in self.profiles if p['phase']=='initial'],revision=2)

    @staticmethod
    def row_key(row):
        return (row['video_id'],row['need_id'],row['round'],round(row['start'],6),round(row['end'],6),row.get('query_mode','main'),row['audit'])

    def metric(self,video_id,stage,elapsed,**extra):
        row=dict(video_id=video_id,stage=stage,seconds=elapsed,phase=self.phase,**extra)
        self.metrics.append(row)
        append(self.events/'metrics.jsonl',row)

    def status(self,phase):
        if (self.folder/'stop-request.json').exists():
            raise StopRequested('Creator requested a clean stop')
        super().status(phase)

    def credit(self,need_id,video_id=None):
        ranges={}
        for c in self.candidates:
            if c['need_id']==need_id and c['purpose']=='main' and c['passed']:
                ranges.setdefault(c['video_id'],[]).append([c['start'],c['end']])
        amounts={key:seconds(value) for key,value in ranges.items()}
        if need_id not in self.relaxed:
            amounts={key:min(value,self.targets[need_id]/3) for key,value in amounts.items()}
        return amounts.get(video_id,0) if video_id else sum(amounts.values())

    def remaining(self,need_id,video_id):
        global_left=self.targets[need_id]-self.credit(need_id)
        source_left=self.targets[need_id]-self.credit(need_id,video_id) if need_id in self.relaxed else self.targets[need_id]/3-self.credit(need_id,video_id)
        return max(0,min(global_left,source_left))

    def active(self,video,keys=None):
        return [key for key in (video['needs'] if keys is None else keys) if self.remaining(key,video['id'])>=1.5
            and (self.phase!='quota_refill' or self.credit(key,video['id'])>0)]

    def predict(self,video,a,b,fps,questions,sample_from=None):
        if video['id'] in self.frozen:
            raise ValueError('Completed videos are immutable: no model requests allowed')
        identity=dict(version=1,video=video['id'],size=Path(video['path']).stat().st_size,start=round(a,6),end=round(b,6),
            fps=fps,crop=video.get('crop'),context=32768,pins=self.config['model'],questions=questions)
        key=digest(identity)
        result_path=self.tasks/(key+'.result.json')
        if not result_path.exists() and all(q['task']=='grounding' for q in questions):
            for old_key,result,sample in self.lookup.get((video['id'],round(a,6),round(b,6),fps),[]):
                indexed={(q['question']['task'],q['question']['query']):q for q in result['queries']}
                if all((q['task'],q['query']) in indexed for q in questions):
                    reused=copy.deepcopy(result)
                    reused['queries']=[]
                    for q in questions:
                        row=copy.deepcopy(indexed[(q['task'],q['query'])])
                        row['question']=q
                        row['output']['id']=q['id']
                        reused['queries'].append(row)
                    reused.update(id=key,reused_legacy_task=old_key)
                    save_json(result_path,reused)
                    break
        before=len(self.timings)
        key,result=super().predict(video,a,b,fps,questions,sample_from=sample_from)
        for row in self.timings[before:]:
            row.update(phase=self.phase,query_mode=self.query_mode)
            append(self.events/'timings.jsonl',row)
            self.metric(video['id'],'clip_cutting',row['sampling_seconds'],from_round3=bool(sample_from),cache_hit=row['cache_hit'])
            self.metric(video['id'],'task_wait_overhead',row['wait_overhead_seconds'])
            if not row['cache_hit']:
                self.metric(video['id'],'worker_idle_between_tasks',row['worker_idle_before_seconds'])
        return key,result

    def black_ranges(self,video):
        cached=(self.cache/(video['id']+'.black.json')).exists()
        started=time.perf_counter()
        ranges=super().black_ranges(video)
        self.metric(video['id'],'black_scan',0 if cached else time.perf_counter()-started,cache_hit=cached)
        return ranges

    def score_window(self,video,window,number,black,audit=False):
        wanted=[(video['id'],key,number,round(window['start'],6),round(window['end'],6),self.query_mode,audit) for key in window['needs']]
        existing={self.row_key(w):w for w in self.windows}
        if all(key in existing for key in wanted):
            return [existing[key] for key in wanted]
        original=self.needs
        changed={key:dict(n,variants=[]) for key,n in original.items()}
        if self.query_mode=='variants':
            for key in window['needs']:
                alternatives=original[key].get('variants',[])
                changed[key]=dict(original[key],query=alternatives[0],variants=alternatives[1:])
        self.needs=changed
        try:
            rows=super().score_window(video,window,number,black,audit=audit)
        finally:
            self.needs=original
        for row in rows:
            row.update(query_mode=self.query_mode,sampled_clip=dict(self.last_sample))
            append(self.events/'windows.jsonl',row)
        if number==3:
            self.sampled_windows[video['id']].append(dict(self.last_sample))
        return rows

    def quality(self,video,candidate):
        categories=['normal','menu','facecam','logo']
        descriptions=['Normal footage without a menu, facecam or overlaid logo.','A menu or pause screen.',
            'A facecam or webcam, including a picture-in-picture facecam.','A logo or watermark over the picture.']
        order=list(range(4))
        random.Random(self.settings['seed']+int(candidate['id'],16)).shuffle(order)
        options=[chr(65+i)+'. '+descriptions[category] for i,category in enumerate(order)]
        origin=candidate.get('confirmation_parent') or next((w for w in self.sampled_windows[video['id']]
            if w['start']<=candidate['start']+1e-6 and w['end']>=candidate['end']-1e-6),None)
        question=dict(id=candidate['need_id']+'-quality',task='choice',
            query='Which best describes the video picture? Ignore ordinary gameplay HUD and in-world text.',options=options)
        _,result=self.predict(video,candidate['start'],candidate['end'],2.,[question],sample_from=origin)
        output=result['queries'][0]['output']
        normal_index=order.index(0)
        return dict(options=options,probabilities=output['probabilities'],answer_index=output['answer_index'],
            category=categories[order[output['answer_index']]],normal_index=normal_index,
            passed=output['answer_index']==normal_index and output['probabilities'][normal_index]>=.6,
            category_probabilities={categories[category]:output['probabilities'][i] for i,category in enumerate(order)})

    def finish_piece(self,video,candidate):
        candidate.update(revision=2,qc_flags=[],qc=dict(policy='video black scan + quality choice + ffmpeg freeze'),passed=False)
        if not candidate['choice_pass'] or candidate['source_scope_status']=='conflict':
            return candidate
        candidate['quality']=self.quality(video,candidate)
        candidate['sampled_piece_path']=self.last_sample['path']
        if not candidate['quality']['passed']:
            candidate['qc_flags']=['quality:'+candidate['quality']['category']]
            return candidate
        a,b=candidate['start'],candidate['end']
        frozen_path=self.cache/(digest([video['id'],a,b,self.last_sample['path'],'freeze-v2'])+'.freeze.json')
        if frozen_path.exists():
            frozen=json.loads(frozen_path.read_text())
            elapsed=0.
        else:
            frozen=freeze_check(self.last_sample['path'],b-a)
            save_json(frozen_path,frozen)
            elapsed=frozen['seconds']
        self.metric(video['id'],'frozen_check',elapsed)
        candidate['qc'].update(frozen=frozen['frozen'],freeze=frozen)
        candidate['qc_flags']=['frozen'] if frozen['frozen'] else []
        candidate['passed']=not frozen['frozen']
        return candidate

    def check_candidates(self,video,rows,black,purpose):
        pool=[]
        for row in rows:
            for span in self.candidate_ranges(row,black):
                weights=[(max(0,min(span['end'],row['start']+b)-max(span['start'],row['start']+a)),p)
                    for (a,b),p in zip(row['bounds'],row['probabilities'])]
                weight=sum(w for w,p in weights)
                span['grounding']=sum(w*p for w,p in weights)/weight if weight else span['grounding']
                pool.append(dict(span,need_id=row['need_id'],sampled_clip=row.get('sampled_clip')))
        self.pools.setdefault(video['id'],[]).extend(pool)
        for span in sorted(pool,key=lambda c:(-c['grounding'],c['start'],c['need_id'])):
            need_id=span['need_id']
            if purpose=='main':
                remaining=self.remaining(need_id,video['id'])
                if remaining<1.5:
                    continue
                selected=[c for c in self.candidates if c['video_id']==video['id'] and c['need_id']==need_id and c['passed'] and c['purpose']=='main']
                if not spaced(span['start'],span['end'],selected):
                    continue
                a,b=span['start'],min(span['end'],span['start']+remaining)
            else:
                a,b=span['start'],span['end']
            identity=digest([video['id'],need_id,a,b,purpose])
            if identity in self.tested:
                continue
            self.status(f"v2 {video['id']} {purpose}: {need_id} {a:.1f}-{b:.1f}")
            self.confirmation_origin=span.get('sampled_clip')
            candidate=self.confirm(video,need_id,a,b,span['grounding'],purpose)
            candidate=self.finish_piece(video,candidate)
            candidate['handles']=next((r for r in subtract(max(0,a-2),min(video['probe']['duration'],b+2),black)
                if r[0]<=a+1e-6 and r[1]>=b-1e-6),[a,b])
            self.candidates.append(candidate)
            self.tested.add(identity)
            append(self.events/'candidates.jsonl',candidate)

    def ranked(self,windows,rows,number,duration):
        chunks=merge_windows(windows,duration,self.settings['window_seconds'][number-1])
        def priority(window):
            values=[p for row in rows if row['need_id'] in window['needs']
                for (a,b),p in zip(row['bounds'],row['probabilities'])
                if row['start']+b>window['start'] and row['start']+a<window['end']]
            return max(values,default=0)
        return sorted(chunks,key=lambda w:(-priority(w),w['start']))

    def rounds(self,video,black):
        duration=video['probe']['duration']
        active=self.active(video)
        calibration=video['id'] in self.audit_plan and self.query_mode=='main'
        if calibration:
            # Mandatory recall calibration still measures coarse scores after production quotas fill.
            active=list(video['needs'])
        if self.query_mode=='variants':
            active=[key for key in active if self.needs[key].get('variants')]
        if not active:
            return {}
        first=3 if duration<120 else 2 if duration<300 else 1
        queues={first:[dict(start=0.,end=duration,needs=active)]}
        parents={first:[]}
        coarse={key:[] for key in active}
        for number in range(first,4):
            source_rows=[]
            queued=self.ranked(queues.get(number,[]),parents.get(number,[]),number,duration)
            started=time.perf_counter()
            for window in queued:
                keys=window['needs'] if calibration and number==1 else self.active(video,window['needs'])
                if self.query_mode=='variants':
                    keys=[key for key in keys if self.needs[key].get('variants')]
                if not keys:
                    continue
                window=dict(window,needs=keys)
                self.status(f"v2 {video['id']} {self.query_mode} round {number}: {window['start']:.1f}-{window['end']:.1f}; {len(keys)} needs")
                rows=self.score_window(video,window,number,black)
                source_rows.extend(rows)
                if number==3:
                    self.check_candidates(video,rows,black,'main')
            self.metric(video['id'],f'round_{number}',time.perf_counter()-started,query_mode=self.query_mode)
            if number==3:
                continue
            next_windows=[]
            for row in source_rows:
                for span in runs(row['probabilities'],row['bounds'],self.settings['thresholds'][number-1],row['start'],row['black']):
                    padding=self.settings['padding_seconds'][number-1]
                    next_windows.append(dict(start=max(0,span['start']-padding),end=min(duration,span['end']+padding),needs=[row['need_id']]))
            if number==1:
                for key in active:
                    coarse[key]=union([[w['start'],w['end']] for w in next_windows if key in w['needs']])
                bypass={key for key in active if seconds(coarse[key])>duration/2}
                queues[2]=[w for w in next_windows if w['needs'][0] not in bypass]
                queues.setdefault(3,[]).extend(w for w in next_windows if w['needs'][0] in bypass)
                parents[2]=source_rows
                parents.setdefault(3,[]).extend(r for r in source_rows if r['need_id'] in bypass)
                self.metric(video['id'],'round2_bypass',0,needs=sorted(bypass),retained={k:seconds(v) for k,v in coarse.items()})
                planned=merge_windows(queues[2],duration,self.settings['window_seconds'][1])+merge_windows(queues.get(3,[]),duration,self.settings['window_seconds'][2])
                coarse={key:union([[w['start'],w['end']] for w in planned if key in w['needs']]) for key in active}
                if self.query_mode=='main':
                    save_json(self.folder/'coarse-v2'/(video['id']+'.json'),dict(retained=coarse,bypass_round2=sorted(bypass),
                        policy='Planned retained coarse windows, including padding and merged question lists, before quota stopping.'))
            else:
                queues.setdefault(3,[]).extend(next_windows)
                parents.setdefault(3,[]).extend(source_rows)
        return coarse

    def representatives(self,videos):
        for need_id,need in self.needs.items():
            if need.get('manual'):
                continue
            for number,threshold in enumerate(self.settings['thresholds'],1):
                cells=[]
                for row in self.windows:
                    if row['need_id']!=need_id or row['round']!=number or row['audit'] or row.get('query_mode')=='variants':
                        continue
                    for i,p in enumerate(row['probabilities']):
                        if row['black'][i]:
                            continue
                        a,b=row['bounds'][i]
                        cells.append(dict(video_id=row['video_id'],need_id=need_id,round=number,start=row['start']+a,end=row['start']+b,
                            probability=p,fps=row['fps'],sampled_clip=row.get('sampled_clip'),
                            frame_times=[row['start']+min(2*i+j,row['frames']-1)/row['fps'] for j in [0,1]]))
                cells.sort(key=lambda c:(c['video_id'],c['start'],c['end']))
                above=[c for c in cells if c['probability']>=threshold]
                below=sorted([c for c in cells if c['probability']<threshold],key=lambda c:-c['probability'])
                selected=[('random above',c) for c in random.Random(self.settings['seed']+number+int(digest(need_id),16)).sample(above,min(3,len(above)))]
                selected += [('nearest below',c) for c in below[:3]]
                for kind,cell in selected:
                    cell.update(kind=kind,threshold=threshold,context=32768)
                    if need.get('hard'):
                        video=videos[cell['video_id']]
                        if cell['video_id'] in self.frozen:
                            choices=[c for c in self.candidates if c['video_id']==cell['video_id'] and c['need_id']==need_id
                                and c['start']<cell['end'] and c['end']>cell['start']]
                            if choices:
                                cell['choice']=max(choices,key=lambda c:min(c['end'],cell['end'])-max(c['start'],cell['start']))
                                cell['cached_completed_choice']=True
                            else:
                                cell['choice_unavailable_reason']='Completed video is frozen; no cached choice covers this cell.'
                                cell['choice_options']=[need['confirm']['right'],*need['confirm']['wrong'],'None of these.']
                        else:
                            a,b=cell['start'],min(video['probe']['duration'],cell['end'])
                            if b-a<.5:
                                a=max(0,min(a,video['probe']['duration']-1.5))
                                b=min(video['probe']['duration'],max(b,a+1.5))
                            self.status(f"v2 representative: {need_id} {video['id']} {a:.1f}")
                            self.confirmation_origin=cell.get('sampled_clip') if number==3 else None
                            cell['choice']=self.finish_piece(video,self.confirm(video,need_id,a,b,cell['probability'],'representative'))
                    self.representative.append(cell)

    def checkpoint(self):
        if digest([c for c in self.candidates if c['video_id'] in self.frozen])!=self.legacy_fingerprint:
            raise RuntimeError('Frozen completed-video candidates changed')
        save_json(self.folder/'candidates.json',self.candidates)
        save_json(self.folder/'score-windows.json',self.windows)
        save_json(self.folder/'timing-report.json',self.timings)
        save_json(self.folder/'performance-v2.json',dict(videos=self.profiles,metrics=self.metrics,
            targets={key:dict(target_seconds=t,credited_seconds=self.credit(key),cap_lifted=key in self.relaxed) for key,t in self.targets.items()}))

    def process(self,video):
        started=time.perf_counter()
        before=len(self.candidates)
        black=self.black_ranges(video)
        coarse=self.rounds(video,black)
        save_json(self.folder/'coarse'/(video['id']+'.json'),coarse)
        self.state['initial_pass_videos'].append(video['id'])
        profile=dict(video_id=video['id'],input_seconds=video['probe']['duration'],phase=self.phase,
            seconds=time.perf_counter()-started,candidates=len(self.candidates)-before,
            passed=sum(c['passed'] for c in self.candidates[before:]))
        self.profiles.append(profile)
        append(self.events/'videos.jsonl',profile)
        self.checkpoint()
        initial=[p for p in self.profiles if p['phase']=='initial']
        if len(initial)==3:
            summary=dict(videos=initial,total_seconds=sum(p['seconds'] for p in initial),
                input_seconds=sum(p['input_seconds'] for p in initial),metrics=self.metrics,
                note='Initial passes of the first 3 unfinished videos. Deferred quota lifting, variants and mandatory audits are additional work.')
            save_json(self.folder/'speed-first3.json',summary)
            stages={key:sum(m['seconds'] for m in self.metrics if m['stage']==key and m['phase']=='initial')
                for key in ['clip_cutting','black_scan','task_wait_overhead','worker_idle_between_tasks','round_1','round_2','round_3','frozen_check']}
            lines=['# First three unfinished videos: revised speed','',summary['note'],'',
                f"Input: {summary['input_seconds']/60:.2f} min. Processing: {summary['total_seconds']:.2f} s. Throughput: {summary['input_seconds']/max(.001,summary['total_seconds']):.2f}× real time.",'',
                '| Video | Input s | Initial pass s | Pieces tested | Passed |','| --- | ---: | ---: | ---: | ---: |']
            lines += [f"| `{p['video_id']}` | {p['input_seconds']:.3f} | {p['seconds']:.3f} | {p['candidates']} | {p['passed']} |" for p in initial]
            lines += ['', '## Timing breakdown','', 'Round times include their model work, confirmation and substeps. Cutting, waiting and worker idle overlap those round times; do not add the columns as independent totals. Cached black scans add zero new scan time.','']
            lines += ['- '+key+f": {value:.3f} s" for key,value in stages.items()]
            lines += ['', 'This is the new workload with quota stopping and cached partial results, not a controlled rerun of finished videos. The old finished videos were not recomputed.']
            (self.folder/'speed-first3.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

    def logo_controls(self):
        self.phase='logo_controls'
        available=[c for c in self.candidates if c.get('revision')==2 and c['purpose']=='main' and c['passed']
            and c.get('sampled_piece_path') and Path(c['sampled_piece_path']).exists()]
        random.Random(self.settings['seed']).shuffle(available)
        chosen=[]
        for c in available:
            if c['video_id'] not in {x['video_id'] for x in chosen}:
                chosen.append(c)
        chosen=(chosen+[c for c in available if c['id'] not in {x['id'] for x in chosen}])[:10]
        controls=self.cache/'logo-controls'
        controls.mkdir(exist_ok=True)
        results=[]
        for i,candidate in enumerate(chosen):
            size=16 if i%2==0 else 32
            key=digest([candidate['id'],'watermark-control',size])
            path=controls/(key+'.mp4')
            if not path.exists():
                filters=f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='TEST LOGO':x=w-tw-8:y=h-th-8:fontsize={size}:fontcolor=white:borderw=1:bordercolor=black"
                started=time.perf_counter()
                command(['ffmpeg','-v','error','-y','-i',candidate['sampled_piece_path'],'-an','-vf',filters,
                    '-c:v','libx264','-preset','ultrafast','-g','1','-threads','2',str(path)],120)
                self.metric(candidate['video_id'],'logo_control_cut',time.perf_counter()-started)
            control=dict(candidate,id=key,confirmation_parent=dict(path=str(path),start=candidate['start'],end=candidate['end']))
            self.status('Synthetic logo control '+key)
            quality=self.quality(self.videos[candidate['video_id']],control)
            results.append(dict(id=key,video_id=candidate['video_id'],start=candidate['start'],end=candidate['end'],
                font_pixels=size,expected='logo',quality=quality,detected_logo=quality['category']=='logo' and quality['category_probabilities']['logo']>=.6,
                rejected=not quality['passed'],synthetic_path=str(path)))
        report=dict(tested=len(results),detected_logo=sum(r['detected_logo'] for r in results),
            rejected=sum(r['rejected'] for r in results),results=results,
            limitation='Known synthetic corner-watermark positives only; no real-logo recall, specificity or precision claim. Originals and production results are unchanged.')
        save_json(self.folder/'logo-option-report.json',report)
        lines=['# Logo option: known watermark controls','',f"Logo recognized: {report['detected_logo']}/{report['tested']}. Quality gate rejected: {report['rejected']}/{report['tested']}.",'',report['limitation'],'',
            'Controls add TEST LOGO at 16 or 32 pixels to already passed clips from unfinished videos. They are evaluation files only and never enter the candidate pool.','',
            '| Source | Font pixels | Predicted category | Logo probability | Rejected |','| --- | ---: | --- | ---: | --- |']
        lines += [f"| `{r['video_id']}` | {r['font_pixels']} | {r['quality']['category']} | {r['quality']['category_probabilities']['logo']:.4f} | {r['rejected']} |" for r in results]
        (self.folder/'logo-option-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

    def short_summary(self,status,error=None):
        audit_path=self.folder/'miss-audit-report.json'
        audit=json.loads(audit_path.read_text()) if audit_path.exists() else {}
        logo_path=self.folder/'logo-option-report.json'
        logo=json.loads(logo_path.read_text()) if logo_path.exists() else {}
        failures=[dict(id=v['id'],status=v['status']) for v in self.downloads['videos'] if v['status']!='ready']
        summary=dict(status=status,frozen_videos=len(self.frozen),initial_passes=len(self.state['initial_pass_videos']),
            main_candidates=sum(c['purpose']=='main' for c in self.candidates),
            main_passed=sum(c['purpose']=='main' and c['passed'] for c in self.candidates),
            blocked_or_failed_downloads=failures,index_failures=self.state.get('failed_videos',[]),
            audited_sources=audit.get('audited_sources'),coarse_missed_spans=audit.get('coarse_missed_candidate_spans'),
            synthetic_logos_detected=logo.get('detected_logo'),synthetic_logos_tested=logo.get('tested'),
            logo_limit='Synthetic positives only; real-logo accuracy unvalidated.',
            coverage=str(self.folder/'coverage.md'),review=str(self.project/'production/jev-review/review.html'),
            speed_report=str(self.folder/'speed-first3.md'),assignment_started=False,error=error)
        summary['frozen_cache_verified']=self.state.get('frozen_cache_verified',False)
        save_json(self.folder/'stage3-summary.json',summary)
        lines=['# Stage 3 short summary','',f"Status: **{status}**.",'',
            f"Frozen completed videos: {len(self.frozen)}. Revised initial passes: {len(self.state['initial_pass_videos'])}.",
            'Frozen cache integrity: '+('verified.' if self.state.get('frozen_cache_verified') else 'not yet checked.'),
            f"Main candidates passed: {summary['main_passed']} / {summary['main_candidates']}.",
            f"Audited long sources: {summary['audited_sources']}; coarse-missed spans: {summary['coarse_missed_spans']}.",
            f"Synthetic logos recognized: {summary['synthetic_logos_detected']} / {summary['synthetic_logos_tested']}. Real-logo accuracy remains unvalidated.",
            'Downloads blocked/failed: '+', '.join(v['id']+' ('+v['status']+')' for v in failures)+'.',
            'No assignment or new timeline was made.','',
            '[Coverage](coverage.md) · [Three-video speed report](speed-first3.md) · [Logo test](logo-option-report.md) · [Review](../../production/jev-review/review.html)']
        if error:
            lines += ['', 'Error: '+str(error)]
        (self.folder/'stage3-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

    def verify_frozen_cache(self):
        saved=json.loads((self.folder/'candidates.json').read_text(encoding='utf-8'))
        if digest([c for c in saved if c['video_id'] in self.frozen])!=self.legacy_fingerprint:
            raise RuntimeError('Frozen completed-video candidates changed on disk')
        manifest=json.loads((Path(self.policy['checkpoint'])/'immutable-manifest.json').read_text())
        for video_id,expected in manifest['frozen_scores'].items():
            rows=self.db.execute('SELECT * FROM scores WHERE video_id=? ORDER BY query_hash,round,t0,t1,window_id',(video_id,)).fetchall()
            if hashlib.sha256(json.dumps(rows).encode()).hexdigest()!=expected:
                raise RuntimeError('Frozen score cells changed: '+video_id)
        for name,expected in manifest['model_results'].items():
            if hashlib.sha256((self.cache/'tasks'/name).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('Preserved model result changed: '+name)
        self.state['frozen_cache_verified']=True

    def run(self):
        pending=sorted([v for v in self.videos.values() if v['id'] not in self.frozen],key=lambda v:(len(v['needs']),v['probe']['duration'],v['id']))
        save_json(self.folder/'resume-order.json',[v['id'] for v in pending])
        self.status('Starting independent background worker; completed videos remain frozen')
        self.start_worker()
        for video in pending:
            if video['id'] in self.state['initial_pass_videos']:
                continue
            try:
                self.process(video)
            except StopRequested:
                raise
            except Exception as exc:
                if (self.tasks/'fatal.json').exists():
                    raise
                self.state.setdefault('failed_videos',[]).append(dict(id=video['id'],error=str(exc)))
                self.status(video['id']+': '+str(exc))
                self.checkpoint()
        # Every assigned URL has now been tested or reported unavailable/failed.
        self.relaxed={key for key,target in self.targets.items() if self.credit(key)<target-1.5}
        self.phase='quota_refill'
        for video in pending:
            if self.active(video):
                started=time.perf_counter()
                self.rounds(video,self.black_ranges(video))
                self.metric(video['id'],'quota_refill',time.perf_counter()-started)
                self.checkpoint()
        self.phase='variants'
        self.query_mode='variants'
        for video in pending:
            if any(self.needs[key].get('variants') for key in self.active(video)):
                self.rounds(video,self.black_ranges(video))
                self.checkpoint()
        self.query_mode='main'
        self.phase='miss_audit'
        audit_plan=json.loads((self.folder/'miss-audit-plan.json').read_text())['sources']
        for video_id,stretches in audit_plan.items():
            if video_id in self.frozen:
                continue
            video=self.videos[video_id]
            coarse=json.loads((self.folder/'coarse'/(video_id+'.json')).read_text())
            self.audit(video,self.black_ranges(video),stretches,coarse)
            self.checkpoint()
        self.phase='representatives'
        self.representatives(self.videos)
        save_json(self.folder/'representatives.json',self.representative)
        self.checkpoint()
        self.logo_controls()
        self.checkpoint()
        review_python=Path.home()/'AppData/Local/SpearFia/cache/videojev/venv-win/Scripts/python.exe'
        command([str(review_python),str(Path(__file__).with_name('stage3_review.py')),'--project',str(self.project)],3600)
        report=json.loads((self.folder/'miss-audit-report.json').read_text())
        self.verify_frozen_cache()
        self.state['completed_videos']=sorted(self.frozen|{v['id'] for v in pending if v['id'] not in {f['id'] for f in self.state.get('failed_videos',[])}})
        self.state['status']='stage3_gate_ready' if report['gate_complete'] else 'stage3_gate_incomplete'
        self.short_summary(self.state['status'])
        self.status('Stage 3 gate; no assignment performed')


def run(project):
    index=BudgetIndexer(project)
    try:
        index.run()
    except StopRequested:
        index.checkpoint()
        index.state.update(status='stopped_by_creator',phase='Clean stop requested',updated=time.time())
        save_json(index.folder/'index-status.json',index.state)
        index.short_summary('stopped_by_creator')
    except Exception as exc:
        index.checkpoint()
        index.state.update(status='failed',error=str(exc),phase='Failed; results preserved',updated=time.time())
        save_json(index.folder/'index-status.json',index.state)
        index.short_summary('failed',str(exc))
        raise
    finally:
        if index.worker:
            (index.tasks/'stop').touch()
            index.worker.wait(timeout=1800)
        index.db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    project=parser.parse_args().project
    log=Path('C:/SpearFia/cache')/project.name/'stage3-logs'/'resume-v2.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    sys.stdout=sys.stderr=log.open('a',encoding='utf-8',buffering=1)
    try:
        run(project)
    except Exception as exc:
        folder=project/'media'/'jev'
        prior=folder/'index-status.json'
        state=json.loads(prior.read_text()) if prior.exists() else {}
        state.update(status='failed',phase='Failed; results preserved',error=str(exc),updated=time.time())
        save_json(folder/'index-status.json',state)
        summary=folder/'stage3-summary.json'
        if not summary.exists() or json.loads(summary.read_text()).get('error')!=str(exc):
            (folder/'stage3-summary.md').write_text('# Stage 3 short summary\n\nStatus: failed.\n\n'+str(exc)+'\n',encoding='utf-8')
        raise
