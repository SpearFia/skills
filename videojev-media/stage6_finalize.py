# SPDX-License-Identifier: MIT OR Apache-2.0
"""Upgrade only the creator's visible selected masters and save a separate final review."""
import collections
import copy
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

from filmcraft_rpc import FilmCraft
from editing_recipe import native_matches
from script_first import approve,creator_exclusions,read,sha
from stage3_index import digest
from stage3_sources import command,pool,save_json
from stage5_edit import footage_tracks,load_review,master_map,source_spans,visible


class StopRequested(RuntimeError):pass


def media_info(path):
    d=json.loads(command(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],60))
    v=next(s for s in d['streams'] if s['codec_type']=='video');num,den=map(int,v['avg_frame_rate'].split('/'))
    if not num or not den:num,den=map(int,v['r_frame_rate'].split('/'))
    if not num or not den:raise ValueError('Source frame rate is unavailable')
    return dict(width=v['width'],height=v['height'],fps=num/den,duration=float(v.get('duration') or d['format']['duration']),
        video_only=all(s['codec_type']=='video' for s in d['streams']))


def selection(project,data,sequence):
    masters=master_map(project);assets={};exempt=[];unknown=[]
    for a,b,c in visible(footage_tracks(project,sequence)):
        item=data['project']['items'][str(c['item'])];media=item['kind'].get('Media',{});file=media.get('media',{}).get('File',{}).get('path')
        master=masters.get(str(Path(file).resolve()).casefold()) if file else None
        if master is None:
            (exempt if file and Path(file).name in {'title-sting.mp4','end-screen.mp4'} else unknown).append(dict(clip=c['id'],name=c['name'],file=file));continue
        if master['file'] not in assets:
            assets[master['file']]=dict(master=copy.deepcopy(master),items=[],clips=[],old_size=[media['info']['video']['width'],media['info']['video']['height']])
        asset=assets[master['file']]
        if c['item'] not in asset['items']:asset['items'].append(c['item'])
        if c['id'] not in asset['clips']:asset['clips'].append(c['id'])
    return dict(assets=list(assets.values()),generated=exempt,unmapped=unknown)


def crop_filter(master,info):
    c=master.get('crop')
    if not c:return 'setsar=1',None
    pw,ph=master['proxy_size'];w,h=info['width'],info['height']
    x=max(0,min(w-2,2*round(c['x']*w/pw/2)));y=max(0,min(h-2,2*round(c['y']*h/ph/2)))
    cw=min(w-x,max(2,2*round(c['w']*w/pw/2)));ch=min(h-y,max(2,2*round(c['h']*h/ph/2)))
    crop=dict(w=cw,h=ch,x=x,y=y)
    return f'crop={cw}:{ch}:{x}:{y},setsar=1',crop


def scaled_sequence(sequence,items,upgraded):
    expected=copy.deepcopy(sequence);anchors={}
    for track in expected['video_tracks']:
        for c in track['items']:
            if c['item'] not in upgraded:continue
            if not c.get('scale_to_frame'):raise ValueError('Selected footage needs Scale to Frame Size before automatic replacement')
            old=items[str(c['item'])]['kind']['Media']['info']['video'];new=upgraded[c['item']]['info']
            motion=next(e for e in c['effects'] if e['effect']=='motion');param=motion['params']['anchor']
            if param.get('keyframes'):raise ValueError('Animated source anchors require explicit keyframe scaling')
            v=param['value']['Vec2'];v['x']*=new['width']/old['width'];v['y']*=new['height']/old['height'];anchors[c['id']]=[v['x'],v['y']]
    return expected,anchors


def fetch_ranges(assets):
    result=[]
    for a,b in sorted((a['master']['start'],a['master']['end']) for a in assets):
        if result and a<=result[-1]['end']+20 and max(b,result[-1]['end'])-result[-1]['start']<=180:result[-1]['end']=max(b,result[-1]['end'])
        else:result.append(dict(start=a,end=b))
    return result


def blocked(error):
    return bool(re.search(r'age[- ]?(restricted|gated)|confirm your age|sign in|private video|members.only|copyright|HTTP Error (403|429)|too many requests|not a bot|encrypted',str(error),re.I))


def thumb(path,at):
    return subprocess.check_output(['ffmpeg','-v','error','-ss',f'{at:.6f}','-i',str(path),'-frames:v','1','-vf','scale=17:16,format=rgb24','-f','rawvideo','-'],timeout=60)


def frame_error(a,b):
    if len(a)!=816 or len(b)!=816:raise ValueError('Incomplete alignment frame')
    def bits(rgb):
        gray=[(3*rgb[i]+6*rgb[i+1]+rgb[i+2])//10 for i in range(0,816,3)];n=0
        for y in range(16):
            for x in range(16):n=(n<<1)|(gray[y*17+x]>gray[y*17+x+1])
        return n
    color=max(abs(sum(a[c::3])/272-sum(b[c::3])/272) for c in range(3))
    return (bits(a)^bits(b)).bit_count(),color


def alignment(old,new,old_info,new_info):
    duration=min(old_info['duration'],new_info['duration']);rows=[];step=1/old_info['fps']
    for fraction in [.25,.5,.75]:
        at=duration*fraction;expected=thumb(old,at);options=[]
        for shift in [0,-step,step]:
            t=max(0,min(new_info['duration']-1/new_info['fps'],at+shift));distance,color=frame_error(expected,thumb(new,t))
            options.append(dict(shift_seconds=shift,hash_distance=distance,color_error=color))
        best=min(options,key=lambda r:(r['hash_distance'],r['color_error']));best['at']=at;best['matched']=best['hash_distance']<=60 and best['color_error']<=35;rows.append(best)
    if sum(r['matched'] for r in rows)<2:raise ValueError('High-resolution master does not match the proxy source time/crop: '+str(rows))
    return rows


def cut_master(project,asset,source,t0,source_info,cache,fragment=False):
    m=asset['master'];old=project/m['file'];key=digest([1,m['video_id'],m['start'],m['end'],m.get('crop'),m['proxy_size'],old.stat().st_size])
    receipt=cache/'masters'/(key+'.json')
    if receipt.exists():
        result=read(receipt)
        saved=project/result['file']
        if saved.is_file() and saved.stat().st_size==result['bytes'] and result['source_size']==[source_info['width'],source_info['height']]:return result
    output=project/'B-roll/jev-hq'/(Path(m['file']).stem+'-'+key[:8]+'.mp4');output.parent.mkdir(parents=True,exist_ok=True)
    vf,crop=crop_filter(m,source_info);seek=m['start']-t0
    if seek<-.000001:raise ValueError('HLS segment starts after the selected source range')
    temporary=cache/(key+'.working.mp4');started=time.perf_counter()
    at=['-i',str(source),'-ss',f'{max(0,seek):.6f}'] if fragment else ['-ss',f'{max(0,seek):.6f}','-i',str(source)]
    command(['ffmpeg','-v','error','-y','-threads','2',*at,'-t',f"{m['end']-m['start']:.6f}",'-an','-vf',vf,
        '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-threads','2',str(temporary)],900)
    info=media_info(temporary);old_info=media_info(old)
    if not info['video_only'] or abs(info['duration']-old_info['duration'])>max(.1,2/old_info['fps']):raise ValueError('Master duration/streams changed')
    checks=alignment(old,temporary,old_info,info)
    if output.exists():
        index=2
        while output.with_name(output.stem+f'-{index}.mp4').exists():index+=1
        output=output.with_name(output.stem+f'-{index}.mp4')
    shutil.copy2(temporary,output)
    result=dict(file=output.relative_to(project).as_posix(),original_file=m['file'],video_id=m['video_id'],source_start=m['start'],source_end=m['end'],
        crop=crop,source_size=[source_info['width'],source_info['height']],info=info,source_1080p=source_info['height']>=1080 or source_info['width']>=1920,
        alignment=checks,seconds=time.perf_counter()-started,source_offset=t0,bytes=output.stat().st_size)
    save_json(receipt,result);return result


def render_checks(project,before,after,sequence,upgraded,status):
    candidates=[c for t in sequence['video_tracks'] for c in t['items'] if c['item'] in upgraded and c['enabled']]
    cases=[]
    for label,predicate in [('normal',lambda c:True),('slow',lambda c:c['speed']!=1),
        ('zoom',lambda c:any(e['effect']=='motion' and e['params'].get('scale',{}).get('keyframes') for e in c['effects']))]:
        clip=next((c for c in candidates if predicate(c)),None)
        if clip:cases.append(dict(label=label,clip=clip['id'],time=clip['start']+clip['duration']//2))
    out=project/'production/jev-stage6';out.mkdir(exist_ok=True)
    for label,path in [('before',before),('after',after)]:
        with FilmCraft() as f:
            f.command('file.open',path=str(path))
            for case in cases:
                status('Render '+case['label']+' '+label+' framing check')
                f.command('file.exportFrame',path=str(out/(case['label']+'-'+label+'.png')),format='png',target='program',time=case['time'])
    for case in cases:
        distance,color=frame_error(thumb(out/(case['label']+'-before.png'),0),thumb(out/(case['label']+'-after.png'),0))
        case.update(hash_distance=distance,color_error=color,matched=distance<=64 and color<=35)
    return cases


class Finalize:
    def __init__(self,project,review):
        self.project=project;self.document=approve(project);self.review=review;self.input_sha=sha(review);self.root=project/'media/jev/script-first/stage6';self.folder=self.root/self.input_sha[:16];self.folder.mkdir(parents=True,exist_ok=True)
        self.input=self.folder/'creator-saved-edit.fcproj'
        if not self.input.exists():shutil.copy2(review,self.input)
        if sha(self.input)!=self.input_sha:raise ValueError('Saved edit snapshot changed')
        self.data,self.sequence=load_review(project,self.input);self.plan=selection(project,self.data,self.sequence);save_json(self.folder/'selection.json',self.plan)
        self.videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
        if any(a['master']['video_id'] not in self.videos for a in self.plan['assets']):raise ValueError('A selected master lacks its source record')
        self.cache=pool.cache_dir(project)/'jev-stage6';self.cache.mkdir(parents=True,exist_ok=True)
        self.results=read(self.folder/'masters.json') if (self.folder/'masters.json').exists() else {}
        self.state=read(self.folder/'run.json') if (self.folder/'run.json').exists() else dict(started=time.time(),sources_done=[],timings=[])
        self.state.update(status='stage6_running',pid=os.getpid(),input_review=str(review),input_sha256=self.input_sha,stage7_started=False);self.state.pop('error',None)
        original=Path(self.document['approved_script']).parent.parent
        self.protected=[self.input]+[original/n for n in ['project.json','links.json','script/script.md','visuals/visuals.md']]
        self.protected += [project/n for n in ['links.json','media/jev/candidates.json','media/jev/score-windows.json','media/jev/script-first/stage4/assignment.json']]
        self.before={str(f):sha(f) for f in self.protected}

    def summary(self):
        self.state.update(elapsed_seconds=time.time()-self.state['started'],selected_masters=len(self.plan['assets']),selected_sources=len({a['master']['video_id'] for a in self.plan['assets']}),
            selected_clips=sum(len(a['clips']) for a in self.plan['assets']),upgraded_masters=sum(r.get('status')=='upgraded' for r in self.results.values()),
            failures=[dict(file=k,error=r['error']) for k,r in self.results.items() if r.get('status')=='failed'])
        save_json(self.folder/'masters.json',self.results);save_json(self.folder/'run.json',self.state);save_json(self.root/'run.json',self.state)
        lines=['# Stage 6 — short summary','',f"Status: **{self.state['status']}**. Phase: {self.state.get('phase','starting')}.",'',
            f"Input: `{self.review}`. A byte-identical snapshot is preserved; only this saved edit's visible footage is selected.",'',
            f"Selected: {self.state['selected_clips']} footage placements, {self.state['selected_masters']} masters, {self.state['selected_sources']} sources. "
            f"Upgraded masters: {self.state['upgraded_masters']}. Failed masters: {len(self.state['failures'])}. Elapsed: {self.state['elapsed_seconds']/60:.1f} min.",'',
            'The creator authorized Stage 6 after reviewing the third Stage 5 test. Stage 5 test footage is not inserted into this selected edit. No re-assignment or new VideoJev inference. Stage 7 has not started.']
        if self.state.get('final_review'):lines+=['',f"Final review: `{self.state['final_review']}`."]
        if self.state.get('verification'):lines+=['',f"Checks: `{self.folder/'verification.json'}`. Timing, retiming, zooms, captions and audio are checked against the saved edit; source anchors are scaled for the replacement resolution."]
        if self.state.get('verification',{}).get('edited_file_changed_since_snapshot'):lines+=['','The edited file changed after the captured snapshot. This final review uses the earlier saved snapshot.']
        if self.plan['unmapped']:lines+=['',f"Unmapped selected media: {len(self.plan['unmapped'])}; source lineage is needed for an upgrade."]
        failed_frames=[r['label'] for r in self.state.get('verification',{}).get('rendered_framing_samples',[]) if not r['matched']]
        if failed_frames:lines+=['','Framing render checks need review: '+', '.join(failed_frames)+'.']
        if self.state['failures']:lines+=['','Failed sources/masters: '+ '; '.join(r['file']+': '+r['error'][:130] for r in self.state['failures'][:8])]
        if self.state.get('under_1080p'):lines+=['',f"Below 1080p: {len(self.state['under_1080p'])} masters; details in the report. No low-resolution file is presented as genuine 1080p."]
        if self.state.get('verification',{}).get('selected_quality_flags'):lines+=['',f"Quality review: {len(self.state['verification']['selected_quality_flags'])} selected placements intersect outro exclusions. Your selected edit was preserved; timestamps are in verification.json."]
        if self.state.get('error'):lines+=['','Error: '+self.state['error'][:1200]]
        (self.project/'production/jev-stage6-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

    def status(self,phase):
        if (self.root/'stop').exists():raise StopRequested('Creator requested stop; completed downloads and cuts retained')
        self.state['phase']=phase;self.summary();print(phase,flush=True)

    def download(self,video,assets):
        cache=self.cache/'sources'/video['id'];cache.mkdir(parents=True,exist_ok=True);ranges=fetch_ranges(assets);manifest=cache/(digest(ranges)+'.parts.json')
        manifests=[cache/'full-source.parts.json',manifest]+list(cache.glob('*.parts.json'))
        for saved in dict.fromkeys(manifests):
            if not saved.exists():continue
            parts=[p for p in read(saved) if Path(p['path']).is_file()]
            if all(any(p['start']<=r['start'] and p['end']>=r['end'] for p in parts) for r in ranges):return parts
        try:
            fetched=pool.stream_clips(video['url'],ranges,cache)
            parts=[dict(path=str(p),offset=t0,start=r['start'],end=r['end'],kind='hls') for r,(p,t0) in zip(ranges,fetched)]
            if len(parts)!=len(ranges):raise ValueError('Not every selected source range was fetched')
            info=media_info(parts[0]['path'])
            if info['height']<1080 and info['width']<1920:raise ValueError('HLS source is below 1080p; try the full-quality format')
        except (Exception,SystemExit) as exc:
            if blocked(exc):raise RuntimeError('Blocked source; no bypass or retry: '+str(exc)) from exc
            self.status('HLS unavailable; fetch full-quality source '+video['id'])
            source=pool.fetch(video['url'],cache,full=True)[0];parts=[dict(path=str(source),offset=0,start=0,end=video['probe']['duration'],kind='full')]
        save_json(manifest,parts)
        if all(p['kind']=='full' for p in parts):save_json(cache/'full-source.parts.json',parts)
        return parts

    def process_source(self,video,assets):
        missing=[a for a in assets if self.results.get(a['master']['file'],{}).get('status')!='upgraded']
        if not missing:return
        self.status('Fetch selected ranges from '+video['id']);started=time.perf_counter()
        try:
            if video.get('age_limit',0):raise RuntimeError('Age-gated source; no bypass')
            parts=self.download(video,missing)
            source_info={p['path']:media_info(p['path']) for p in parts}
            def cut(a):
                m=a['master'];part=next(p for p in parts if p['start']<=m['start']+1e-6 and p['end']>=m['end']-1e-6)
                return cut_master(self.project,a,Path(part['path']),part['offset'],source_info[part['path']],self.cache,fragment=part['kind']=='hls')
            failures=[]
            with ThreadPoolExecutor(max_workers=2) as workers:
                jobs={workers.submit(cut,a):a for a in missing}
                for future in as_completed(jobs):
                    a=jobs[future];file=a['master']['file']
                    try:self.results[file]=dict(status='upgraded',**future.result())
                    except Exception as exc:failures.append(a);self.results[file]=dict(status='failed',error=str(exc),video_id=video['id'])
                    self.status('Cut/validate high-resolution master '+file)
            if failures and any(p['kind']=='hls' for p in parts):
                self.status('HLS cut validation failed; try full source '+video['id'])
                source=pool.fetch(video['url'],self.cache/'sources'/video['id'],full=True)[0];info=media_info(source)
                save_json(self.cache/'sources'/video['id']/'full-source.parts.json',[dict(path=str(source),offset=0,start=0,end=video['probe']['duration'],kind='full')])
                for a in failures:
                    file=a['master']['file']
                    try:self.results[file]=dict(status='upgraded',**cut_master(self.project,a,source,0,info,self.cache))
                    except Exception as exc:self.results[file]=dict(status='failed',error=str(exc),video_id=video['id'])
                    self.status('Validate full-source master '+file)
        except StopRequested:raise
        except (Exception,SystemExit) as exc:
            for a in missing:
                file=a['master']['file']
                if self.results.get(file,{}).get('status')!='upgraded':self.results[file]=dict(status='failed',video_id=video['id'],error=str(exc))
            if '429' in str(exc) or 'too many requests' in str(exc).lower() or 'not a bot' in str(exc).lower():raise RuntimeError('Source service blocked requests; completed work retained. No request loop.') from exc
        self.state['sources_done']=list(dict.fromkeys(self.state['sources_done']+[video['id']]))
        self.state['timings'].append(dict(video_id=video['id'],seconds=time.perf_counter()-started,masters=len(missing)));self.summary()

    def build(self):
        upgraded={item:self.results[a['master']['file']] for a in self.plan['assets'] if self.results.get(a['master']['file'],{}).get('status')=='upgraded' for item in a['items']}
        expected,anchors=scaled_sequence(self.sequence,self.data['project']['items'],upgraded)
        existing=self.folder/'build.json'
        if existing.exists() and Path(read(existing)['review']).is_file():target=Path(read(existing)['review'])
        else:
            target=self.review.with_name(self.review.stem+'-final.fcproj');index=2
            while target.exists():target=self.review.with_name(self.review.stem+f'-{index}-final.fcproj');index+=1
            with FilmCraft() as f:
                f.command('file.open',path=str(self.input))
                for item,result in upgraded.items():f.command('media.relink',item=item,path=str(self.project/result['file']),force=True,relinkOthers=False,alignTimecode=False)
                for clip,anchor in anchors.items():f.command('effects.setParam',clip=clip,effect='motion',param='anchor',value=anchor)
                f.command('file.saveAs',path=str(target));save_json(self.folder/'native-snapshot.json',f.tool('sequence_inspect',{}))
        actual,sequence=load_review(self.project,target)
        if not native_matches(expected,sequence,anchors):raise AssertionError('Native sequence changed beyond resolution-adjusted source anchors')
        for item,result in upgraded.items():
            media=actual['project']['items'][str(item)]['kind']['Media'];assert Path(media['media']['File']['path']).resolve()==(self.project/result['file']).resolve()
            assert (media['info']['video']['width'],media['info']['video']['height'])==(result['info']['width'],result['info']['height'])
        save_json(existing,dict(review=str(target),anchors_adjusted=len(anchors),items_relinked=len(upgraded)))
        return str(target),sequence,upgraded

    def run(self):
        try:
            grouped=collections.defaultdict(list)
            for a in self.plan['assets']:grouped[a['master']['video_id']].append(a)
            for vid in sorted(grouped,key=lambda v:self.videos[v]['probe']['duration']):
                self.process_source(self.videos[vid],grouped[vid]);time.sleep(.5)
            self.status('Relink chosen masters and preserve native edit geometry');target,expected,upgraded=self.build()
            self.status('Verify exact native sequence and upgraded media')
            final,seq=load_review(self.project,Path(target));assert seq==expected
            assert set(upgraded)<={i for a in self.plan['assets'] for i in a['items']}
            rendering=render_checks(self.project,self.input,Path(target),self.sequence,upgraded,self.status)
            assert all(sha(p)==h for p,h in self.before.items()),'Protected input changed'
            under=[dict(file=k,source_size=r['source_size']) for k,r in self.results.items() if r.get('status')=='upgraded' and not r['source_1080p']]
            flags=[];excluded=creator_exclusions(self.project)
            for s in source_spans(self.project,self.data,footage_tracks(self.project,self.sequence)):
                if any(a<s['end'] and b>s['start'] for a,b in excluded.get(s['video_id'],[])):flags.append(s)
            verification=dict(native_sequence_matches_exactly_except_scaled_source_anchors=True,audio_captions_cards_transitions_zooms_speeds_preserved=True,
                pixel_coordinate_roundtrip_tolerance=1e-9,
                fetched_only_selected_masters=True,selected_master_count=len(self.plan['assets']),upgraded_items=len(upgraded),input_snapshot_unchanged=True,
                edited_file_changed_since_snapshot=not self.review.exists() or sha(self.review)!=self.input_sha,selected_quality_flags=flags,unmapped=self.plan['unmapped'],under_1080p=under,
                original_project_unchanged=True,rendered_framing_samples=rendering,
                visual_checks='Per-master three-point source/crop fingerprint checks; source-anchor scaling calibrated against actual FilmCraft rendering')
            save_json(self.folder/'verification.json',verification)
            self.state.update(status='stage6_gate_ready' if len(upgraded)==sum(len(a['items']) for a in self.plan['assets']) and not under and not self.plan['unmapped'] and not verification['edited_file_changed_since_snapshot'] and all(r['matched'] for r in rendering) else 'stage6_gate_incomplete',
                final_review=target,verification=verification,under_1080p=under,phase='Stopped before Stage 7; review final project')
            save_json(self.folder/'report.json',self.state)
        except StopRequested as exc:self.state.update(status='stage6_stopped',phase=str(exc))
        except Exception as exc:self.state.update(status='stage6_failed',error=str(exc));raise
        finally:self.summary()


def run(project,review):
    import msvcrt
    approve(project);root=project/'media/jev/script-first/stage6';root.mkdir(exist_ok=True)
    with (root/'finalize.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Stage 6 is already running') from exc
        try:Finalize(project,review).run()
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
