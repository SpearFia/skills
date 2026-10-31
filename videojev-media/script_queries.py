# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run only the uncached approved video/question pairs, then stop for review."""
import collections
import copy
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

from script_first import approve,questions,read,sha
from stage3_index import Indexer,digest,merge_windows,runs,subtract,union
from stage3_sources import command,pool,save_json


class StopRequested(Exception):pass


def option_text(value):return re.sub(r'^[A-Z]\.\s*','',value).strip().casefold()


def choice_question(qid,text,video_id,start,end):
    labels=[text,'The described content is not visible.','The picture is too unclear to decide.']
    random.Random(int(digest([text,video_id,round(start,6),round(end,6),264731]),16)).shuffle(labels)
    return dict(id=qid+'-choice',task='choice',query='Which statement best matches the visible picture?',
        options=[chr(65+i)+'. '+label for i,label in enumerate(labels)])


def safe_context(a,b,duration,excluded):
    mid=(a+b)/2
    for lo,hi in subtract(0,duration,excluded):
        if lo<=mid<hi and hi-lo>=1.5:
            length=min(hi-lo,max(1.5,b-a));start=max(lo,min(mid-length/2,hi-length))
            return start,start+length
    return None


def confirmation_parent(parent,a,b):
    return parent if parent and parent['fps']==2 and parent['start']<=a+1e-6 and parent['end']>=b-1e-6 and Path(parent['path']).exists() else None


def candidate_spans(rows,excluded):
    found=[]
    for r in rows:
        for span in runs(r['probabilities'],r['bounds'],.5,r['start'],r['black']):
            for a,b in subtract(span['start'],span['end'],excluded):
                if b-a<1.5:continue
                count=math.ceil((b-a)/12)
                for i in range(count):
                    lo=a+(b-a)*i/count;hi=a+(b-a)*(i+1)/count
                    found.append(dict(start=lo,end=hi,grounding=span['mean'],parent=r.get('sampled_clip')))
    return sorted(found,key=lambda c:(-c['grounding'],c['start']))


def spaced_examples(rows,maximum=3):
    result=[]
    for r in rows:
        if all(r['end']+4<=p['start'] or r['start']>=p['end']+4 for p in result):result.append(r)
        if len(result)==maximum:break
    return result


def retained(rows,number,duration,settings):
    output=[]
    for r in rows:
        for span in runs(r['probabilities'],r['bounds'],settings['thresholds'][number-1],r['start'],r['black']):
            pad=settings['padding_seconds'][number-1]
            output.append(dict(start=max(0,span['start']-pad),end=min(duration,span['end']+pad),needs=[r['question_id']]))
    return output


class ScriptQueries(Indexer):
    # The shared worker/sampler is reused; the legacy constructor and cue plan are not.
    def __init__(self,project):
        self.project=project;self.document=approve(project)
        self.root=project/'media/jev/script-first';self.folder=self.root/'query-results';self.folder.mkdir(exist_ok=True)
        if any(p['status']!='ready' for p in read(self.root/'general-pools.json')):raise ValueError('General pools are not ready')
        self.qs=questions(self.document);self.plan=read(self.root/'job-plan.json')
        self.allowed={(j['video_id'],j['question_id']) for j in self.plan['model_jobs']}
        if any(j['status']!='new_query' or j['video_id']=='tJbzMqJGH4k' for j in self.plan['model_jobs']):raise ValueError('Invalid new-query queue')
        self.videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
        self.excluded={}
        for p in read(self.root/'general-pools.json'):
            for v in p['videos']:self.excluded[v['video_id']]=union(v['black_ranges']+v['text_ranges'])
        if any(v not in self.excluded for v,q in self.allowed):raise ValueError('A new-query source lacks completed quality scans')
        self.cache=pool.cache_dir(project)/'jev-script-first';self.cache.mkdir(exist_ok=True)
        self.tasks=self.cache/'tasks';self.tasks.mkdir(exist_ok=True)
        self.config=read(Path(__file__).with_name('config.json'));self.settings=self.config['index']
        self.worker=None;self.last_sample=None
        self.windows=read(self.folder/'score-windows.json') if (self.folder/'score-windows.json').exists() else []
        self.candidates=read(self.folder/'candidates.json') if (self.folder/'candidates.json').exists() else []
        self.timings=read(self.folder/'timings.json') if (self.folder/'timings.json').exists() else []
        self.lookup=read(self.folder/'prediction-cache.json') if (self.folder/'prediction-cache.json').exists() else {}
        self.coarse=read(self.folder/'coarse.json') if (self.folder/'coarse.json').exists() else {}
        self.state=read(self.folder/'state.json') if (self.folder/'state.json').exists() else dict(status='running',started=time.time(),completed_videos=[],profiles=[])
        self.state.setdefault('failed_videos',[])
        self.state.pop('error',None)
        self.state.update(status='running',pid=os.getpid(),stage5=False,assignment_started=False)
        fingerprints={name:sha(self.root/name) for name in ['beats.json','questions.json','sources.json','job-plan.json']}
        fingerprints['model_config']=sha(Path(__file__).with_name('config.json'))
        manifest=self.folder/'input-manifest.json'
        if manifest.exists() and read(manifest)!=fingerprints:raise ValueError('The approved run inputs changed; existing results were preserved')
        if not manifest.exists():save_json(manifest,fingerprints)
        self.frozen_paths=[project/name for name in ['links.json','media/jev/needs.json','media/jev/candidates.json','media/jev/score-windows.json','media/jev/assignment.json']]
        self.frozen_hashes={str(p):sha(p) for p in self.frozen_paths}
        if not (self.folder/'general-pools-summary.md').exists():shutil.copy2(project/'production/jev-script-first-summary.md',self.folder/'general-pools-summary.md')

    def checkpoint(self):
        for name,value in [('score-windows',self.windows),('candidates',self.candidates),('prediction-cache',self.lookup),('timings',self.timings),('coarse',self.coarse)]:save_json(self.folder/(name+'.json'),value)
        save_json(self.folder/'state.json',self.state)

    def status(self,phase):
        if (self.folder/'stop').exists():raise StopRequested('Creator requested a clean stop')
        self.state.update(phase=phase,updated=time.time(),windows=len(self.windows),candidates=len(self.candidates))
        save_json(self.folder/'state.json',self.state);self.summary()
        print(phase,flush=True)

    def summary(self):
        self.state['elapsed_seconds']=time.time()-self.state['started']
        audits=read(self.folder/'miss-audit.json') if (self.folder/'miss-audit.json').exists() else {}
        review=self.project/'production/jev-script-query-review/review.html'
        self.state['review']=str(review) if review.exists() else None
        save_json(self.root/'query-run.json',self.state)
        lines=['# Script-first query run — short summary','',f"Status: **{self.state['status']}**. Phase: {self.state.get('phase','startup')}.",'',
            f"New work: {len(self.allowed)} uncached video/question pairs; {len(self.state['completed_videos'])}/{len({v for v,q in self.allowed})} videos complete. Previously cached pairs are reused without new model calls.",'',
            f"Saved new score windows: {len(self.windows)}. Choice samples: {len(self.candidates)}. All 10 general pools remain ready.",'',
            f"Elapsed: {self.state['elapsed_seconds']/60:.1f} min. New-run peak allocated VRAM: {self.state.get('peak_allocated_mib',0):.1f} MiB. Failed videos: {len(self.state['failed_videos'])}.",'',
            'Blocked: `tJbzMqJGH4k` is age-gated; replacement needed. No bypass or retry.','',
            f"Miss audit: {len(audits.get('sources',[]))} long sources; {len(audits.get('dropped_matches',[]))} model-confirmed sampled spans outside coarse retention.",'',
            'Named-scene identity remains for creator review. A model match is not scene identity verification. No new assignment, timeline or Stage 5 operation was performed.']
        if self.state['failed_videos']:lines+=['','Failed videos: '+', '.join(c['video_id']+': '+c['error'][:180] for c in self.state['failed_videos'])]
        if self.state.get('error'):lines+=['','Error: '+self.state['error'][:1000]]
        if review.exists():lines+=['',f'Review: `{review}`.']
        if (self.folder/'speed-first3.md').exists():lines+=['',f"First-three speed report: `{self.folder/'speed-first3.md'}`."]
        (self.project/'production/jev-script-first-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

    def predictions(self,video,a,b,fps,wanted,parent=None):
        self.status(f"{video['id']} {fps:g} fps {a:.1f}–{b:.1f}: {len(wanted)} questions")
        for q in wanted:
            qid=q['id'].split('-')[0]
            if q['task'] not in {'grounding','choice'}:raise ValueError('Unsupported approved-query task')
            if (video['id'],qid) not in self.allowed:raise ValueError('Refusing to rescore a cached or unapproved pair')
            if q['task']=='grounding' and q['query']!=self.qs[qid]['query']:raise ValueError('Query differs from approved beat')
            if q['task']=='choice' and q!=choice_question(qid,self.qs[qid]['query'],video['id'],a,b):raise ValueError('Choice differs from approved template')
        answers=[];missing={};keys={}
        for q in wanted:
            ident=digest([video['id'],Path(video['path']).stat().st_size,video.get('crop'),round(a,6),round(b,6),fps,32768,self.config['model'],q['task'],q['query'],q.get('options')])
            keys[q['id']]=ident
            entry=self.lookup.get(ident)
            if entry and Path(entry['result']).exists():
                result=read(entry['result'])
                answer=next((r for r in result.get('queries',[]) if r['question']['id']==entry['native_question_id']),None)
                if result.get('status')=='complete' and answer:
                    original=answer['question']['id'];answer=copy.deepcopy(answer);answer['question']=q;answer['output']['id']=q['id']
                    answers.append(dict(answer=answer,record=result['record'],sample=entry['sample'],result=entry['result'],native_question_id=original));continue
            missing.setdefault(ident,q)
        if missing:
            if self.worker is None:self.start_worker()
            parent=confirmation_parent(parent,a,b)
            task,result=super().predict(video,a,b,fps,list(missing.values()),sample_from=parent)
            peak=max([result.get('encode_peak_allocated_mib',0)]+[q.get('peak_allocated_mib',0) for q in result['queries']])
            self.state['peak_allocated_mib']=max(self.state.get('peak_allocated_mib',0),peak)
            by_key={}
            for answer in result['queries']:
                entry=dict(result=str(self.tasks/(task+'.result.json')),sample=dict(self.last_sample),native_question_id=answer['question']['id'])
                self.lookup[keys[answer['question']['id']]]=entry
                by_key[keys[answer['question']['id']]]=answer
            already={a['answer']['question']['id'] for a in answers}
            for q in wanted:
                if q['id'] in already:continue
                original=by_key[keys[q['id']]];answer=copy.deepcopy(original);answer['question']=q;answer['output']['id']=q['id']
                answers.append(dict(answer=answer,record=result['record'],sample=dict(self.last_sample),result=str(self.tasks/(task+'.result.json')),native_question_id=original['question']['id']))
            save_json(self.folder/'prediction-cache.json',self.lookup)
            save_json(self.folder/'timings.json',self.timings)
        return answers

    def score(self,video,window,number,audit=False):
        fps=self.settings['fps'][number-1]
        wanted=[dict(id=q+'-v0',task='grounding',query=self.qs[q]['query']) for q in window['needs']]
        answers=self.predictions(video,window['start'],window['end'],fps,wanted)
        rows=[]
        for item in answers:
            record=item['record'];answer=item['answer'];qid=answer['question']['id'].split('-')[0]
            probabilities=answer['output']['probabilities'];duration=window['end']-window['start']
            bounds=[[lo,min(hi,duration)] for lo,hi in record['score_bounds']]
            if len(bounds)!=len(probabilities) or any(hi<=lo for lo,hi in bounds):raise ValueError('Native score bounds are invalid')
            if any(not math.isfinite(p) or not 0<=p<=1 for p in probabilities):raise ValueError('Invalid grounding score')
            black=[any(lo<=window['start']+min(2*i+j,record['frames']-1)/fps<hi for j in [0,1] for lo,hi in self.excluded[video['id']]) for i in range(len(bounds))]
            r=dict(video_id=video['id'],question_id=qid,round=number,audit=audit,start=window['start'],end=window['end'],fps=fps,
                probabilities=probabilities,bounds=bounds,black=black,frames=record['frames'],sampled_clip=item['sample'],
                provenance=dict(result=item['result'],native_question_id=item['native_question_id'],native_query=answer['question']['query']),scene_confirmed=False)
            identity=(qid,video['id'],number,audit,r['start'],r['end'])
            if not any((x['question_id'],x['video_id'],x['round'],x['audit'],x['start'],x['end'])==identity for x in self.windows):self.windows.append(r)
            rows.append(r)
        save_json(self.folder/'score-windows.json',self.windows)
        return rows

    def confirm(self,video,qid,span,purpose):
        ident=digest([video['id'],qid,round(span['start'],6),round(span['end'],6),purpose])
        existing=next((c for c in self.candidates if c['id']==ident),None)
        if existing:return existing
        question=choice_question(qid,self.qs[qid]['query'],video['id'],span['start'],span['end']);options=question['options']
        right=next(i for i,v in enumerate(options) if option_text(v)==self.qs[qid]['query'].casefold().strip())
        result=self.predictions(video,span['start'],span['end'],2.,[question],parent=span.get('parent'))[0]['answer']['output']
        c=dict(id=ident,video_id=video['id'],question_id=qid,need_id=qid,start=span['start'],end=span['end'],grounding=span.get('grounding',0),
            purpose=purpose,options=options,probabilities=result['probabilities'],answer_index=result['answer_index'],right_index=right,
            confirmation=result['probabilities'][right],choice_pass=result['answer_index']==right and result['probabilities'][right]>=.6,
            source_scope_status='creator_group_not_independently_verified',scene_confirmed=False)
        self.candidates.append(c);save_json(self.folder/'candidates.json',self.candidates)
        return c

    def process(self,video,qids):
        started=time.perf_counter();duration=video['probe']['duration'];round_times={}
        first=3 if duration<120 else 2 if duration<300 else 1
        queue=[dict(start=0.,end=duration,needs=qids)];direct=[]
        all_fine=[]
        for number in range(first,4):
            tick=time.perf_counter()
            if number==3:queue+=direct
            windows=merge_windows(queue,duration,self.settings['window_seconds'][number-1]);upcoming=[];scored=[]
            for window in windows:
                rows=self.score(video,window,number);scored+=rows
                if number==3:all_fine+=rows
                else:upcoming+=retained(rows,number,duration,self.settings)
            if number==1:
                kept={qid:union([[w['start'],w['end']] for w in upcoming if qid in w['needs']]) for qid in qids}
                self.coarse[video['id']]=kept;save_json(self.folder/'coarse.json',self.coarse)
                bypass={q for q,spans in kept.items() if sum(b-a for a,b in spans)>duration/2}
                direct=[dict(w,needs=[q for q in w['needs'] if q in bypass]) for w in upcoming if any(q in bypass for q in w['needs'])]
                upcoming=[dict(w,needs=[q for q in w['needs'] if q not in bypass]) for w in upcoming if any(q not in bypass for q in w['needs'])]
            queue=upcoming;round_times[str(number)]=time.perf_counter()-tick
        confirmation_started=time.perf_counter()
        for qid in qids:
            rows=[r for r in all_fine if r['question_id']==qid]
            for span in spaced_examples(candidate_spans(rows,self.excluded[video['id']])):self.confirm(video,qid,span,'main')
        self.state['profiles'].append(dict(video_id=video['id'],input_seconds=duration,query_pairs=len(qids),seconds=time.perf_counter()-started,round_seconds=round_times,confirmation_seconds=time.perf_counter()-confirmation_started))
        self.state['failed_videos']=[f for f in self.state['failed_videos'] if f['video_id']!=video['id']]
        self.state['completed_videos'].append(video['id']);self.checkpoint()
        if len(self.state['completed_videos'])==3:
            first3=self.state['profiles'][:3]
            lines=['# First three new-query videos','',f"New queries only, {sum(p['query_pairs'] for p in first3)} video/question pairs; {sum(p['input_seconds'] for p in first3)/60:.2f} input minutes; {sum(p['seconds'] for p in first3):.2f} s processing. Audits and review rendering are additional. First-source time includes worker startup. This is not a controlled rerun of the earlier workload.",'',
                '| Video | New queries | Input s | Processing s |','| --- | ---: | ---: | ---: |']
            lines += [f"| {p['video_id']} | {p['query_pairs']} | {p['input_seconds']:.1f} | {p['seconds']:.2f} |" for p in first3]
            (self.folder/'speed-first3.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

    def audit(self):
        by_video=collections.defaultdict(list)
        for vid,q in self.allowed:by_video[vid].append(q)
        long=sorted((v for v in by_video if v in self.state['completed_videos'] and self.videos[v]['probe']['duration']>=600),key=lambda v:-self.videos[v]['probe']['duration'])[:2]
        if len(long)<2:raise ValueError('Miss audit requires two long new-query sources')
        report=dict(sources=[],dropped_matches=[])
        for vid in long:
            video=self.videos[vid];duration=video['probe']['duration'];record=dict(video_id=vid,stretches=[])
            for fraction in [.15,.5,.85]:
                a=min(duration-30,max(0,duration*fraction));b=a+30
                record['stretches'].append([a,b]);rows=self.score(video,dict(start=a,end=b,needs=sorted(by_video[vid])),3,audit=True)
                for qid in by_video[vid]:
                    for span in spaced_examples(candidate_spans([r for r in rows if r['question_id']==qid],self.excluded[vid]),1):
                        c=self.confirm(video,qid,span,'miss_audit')
                        dropped=sum(y-x for x,y in subtract(c['start'],c['end'],self.coarse.get(vid,{}).get(qid,[])))
                        if c['choice_pass'] and dropped>.1:report['dropped_matches'].append(dict(c,coarse_dropped_seconds=dropped))
            report['sources'].append(record);save_json(self.folder/'miss-audit.json',report)

    def cached_choices(self):
        # Reuse numeric choices only when the old target text exactly equals the approved query.
        by_text=collections.defaultdict(list)
        for q in self.qs.values():by_text[q['query'].casefold().strip()].append(q['id'])
        old=read(self.project/'media/jev/candidates.json');pairs={(j['video_id'],j['question_id']) for j in self.plan['queries'] if j['status']=='reuse_saved_scores'}
        rows=[]
        for c in old:
            right=c['right_index'];target=option_text(c['options'][right])
            for qid in by_text.get(target,[]):
                if (c['video_id'],qid) not in pairs:continue
                if sum(y-x for x,y in subtract(c['start'],c['end'],self.excluded.get(c['video_id'],[])))<c['end']-c['start']-1e-6:continue
                rows.append(dict(id='cached-'+c['id']+'-'+qid,video_id=c['video_id'],question_id=qid,need_id=qid,start=c['start'],end=c['end'],
                    grounding=c.get('grounding',0),purpose='cached',options=c['options'],probabilities=c['probabilities'],
                    answer_index=c['answer_index'],right_index=right,confirmation=c['probabilities'][right],
                    choice_pass=c['answer_index']==right and c['probabilities'][right]>=.6,
                    source_scope_status='creator_group_not_independently_verified',scene_confirmed=False,cached_completed_choice=True))
        return rows

    def representatives(self,all_rows,choices):
        output=[]
        for qid in self.qs:
            cells=[]
            for r in all_rows:
                if r['question_id']!=qid:continue
                number=r.get('round',3 if r['fps']>=1 else 2 if r['fps']>=.4 else 1);threshold=self.settings['thresholds'][number-1]
                for i,p in enumerate(r['probabilities']):
                    a,b=r['bounds'][i];a+=r['start'];b+=r['start']
                    mid=(a+b)/2
                    if r['black'][i] or any(x<b and y>a for x,y in self.excluded.get(r['video_id'],[])):continue
                    cells.append(dict(video_id=r['video_id'],question_id=qid,need_id=qid,start=a,end=b,probability=p,round=number,threshold=threshold,
                        parent=r.get('sampled_clip'),frame_times=[a+(b-a)*.25,a+(b-a)*.75]))
            above=[c for c in cells if c['probability']>=c['threshold']];below=sorted((c for c in cells if c['probability']<c['threshold']),key=lambda c:c['probability']-c['threshold'],reverse=True)
            selected=[]
            if above:selected.append(dict(max(above,key=lambda c:c['probability']),kind='top'))
            rng=random.Random(self.settings['seed']+int(qid,16))
            selected += [dict(c,kind='random above threshold') for c in rng.sample(above,min(3,len(above)))]
            selected += [dict(c,kind='near miss below threshold') for c in below[:2]]
            seen=set()
            for c in selected:
                ident=(c['video_id'],c['start'],c['end'])
                if ident in seen:continue
                seen.add(ident)
                existing=[p for p in choices if p['question_id']==qid and p['video_id']==c['video_id'] and p['start']<=c['start']+1e-6 and p['end']>=c['end']-1e-6]
                if existing:c['choice']=max(existing,key=lambda p:p['confirmation'])
                elif re.search('tank|rhino|helicopter|armory',self.qs[qid]['query'],re.I) and (c['video_id'],qid) in self.allowed:
                    context=safe_context(c['start'],c['end'],self.videos[c['video_id']]['probe']['duration'],self.excluded[c['video_id']])
                    if context:
                        span=dict(start=context[0],end=context[1],grounding=c['probability'],parent=c['parent'])
                        c['choice']=self.confirm(self.videos[c['video_id']],qid,span,'hard_representative')
                if not c.get('choice'):
                    c['choice_unavailable_reason']='No identical saved choice covers this cell. Cached query pairs are not resubmitted.'
                    c['choice_options']=[self.qs[qid]['query'],'The described content is not visible.','The picture is too unclear to decide.']
                output.append(c)
        return output

    def run(self):
        try:
            by_video=collections.defaultdict(list)
            for vid,qid in self.allowed:by_video[vid].append(qid)
            for vid in sorted(by_video):
                if vid in self.state['completed_videos']:continue
                try:self.process(self.videos[vid],sorted(by_video[vid]))
                except StopRequested:raise
                except Exception as exc:
                    if self.worker is None or self.worker.poll() is not None or 'out of memory' in str(exc).lower():raise
                    self.state['failed_videos'].append(dict(video_id=vid,error=str(exc)));self.checkpoint()
            self.audit()
            cached=self.cached_choices();all_rows=read(self.root/'score-reuse.json')['rows']+self.windows
            representative=self.representatives(all_rows,cached+self.candidates)
            save_json(self.folder/'representatives.json',representative);save_json(self.folder/'cached-choices.json',cached)
            self.status('Rendering review sheets');self.state['status']='rendering_review';self.checkpoint();self.summary()
            if self.worker:
                (self.tasks/'stop').touch();self.worker.wait(timeout=1800);self.worker=None
            python=Path.home()/'AppData/Local/SpearFia/cache/videojev/venv-win/Scripts/python.exe'
            command([str(python),str(Path(__file__).with_name('script_query_review.py')),'--project',str(self.project)],1800)
            if any(sha(p)!=h for p,h in self.frozen_hashes.items()):raise ValueError('An existing result or assignment changed')
            self.state.update(status='specific_query_gate_ready_with_failures' if self.state['failed_videos'] else 'specific_query_gate_ready',phase='Review specific matches before assignment')
        except StopRequested as exc:self.state.update(status='stopped_by_creator',phase=str(exc))
        except Exception as exc:self.state.update(status='failed',error=str(exc),phase='Results preserved');raise
        finally:
            self.checkpoint()
            if self.worker:
                (self.tasks/'stop').touch();self.worker.wait(timeout=1800)
            self.summary()


def run(project):
    import msvcrt
    folder=project/'media/jev/script-first';approve(project)
    with (folder/'queries.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Specific-query run is already active') from exc
        try:ScriptQueries(project).run()
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    run(p.parse_args().project.resolve())
