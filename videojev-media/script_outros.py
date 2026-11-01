# SPDX-License-Identifier: MIT OR Apache-2.0
"""Detect the creator-confirmed Movieclips endcard, then retry only the rejected fill."""
import argparse
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from script_first import approve,creator_exclusions,read,sha
from stage3_index import digest
from stage3_sources import save_json
from stage5_check import comparison
from stage5_edit import edit

# shortcut: this template covers Movieclips' split blue endcard; other layouts need their own confirmed examples.
SETTINGS=dict(fps=2,tail_seconds=45,control_seconds=20,min_black_left=.60,min_blue_right=.55,max_rgb_error=12,max_hash_distance=64,min_run_frames=3)


def describe(rgb,at):
    gray=[(3*rgb[j]+6*rgb[j+1]+rgb[j+2])//10 for j in range(0,816,3)];bits=0
    left=[];right=[]
    for y in range(16):
        for x in range(16):bits=(bits<<1)|(gray[y*17+x]>gray[y*17+x+1])
        for x in range(8):left.append(max(rgb[(y*17+x)*3:(y*17+x)*3+3])<45)
        for x in range(9,17):
            i=(y*17+x)*3;right.append(rgb[i+2]>rgb[i]+20 and rgb[i+2]>=rgb[i+1])
    return dict(time=at,rgb=rgb,hash=bits,black_left=sum(left)/len(left),blue_right=sum(right)/len(right))


def samples(video,start,end):
    c=video.get('crop');filters=(f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}," if c else '')+'fps=2:start_time=0:round=up,scale=17:16,format=rgb24'
    data=subprocess.check_output(['ffmpeg','-v','error','-threads','2','-ss',str(start),'-t',str(end-start),'-i',video['path'],'-an','-vf',filters,'-f','rawvideo','-'],timeout=120)
    if len(data)%816:raise ValueError('Incomplete endcard sample')
    return [describe(data[i*816:(i+1)*816],start+i/2) for i in range(len(data)//816) if start+i/2<end]


def matches(frame,anchors):
    if frame['black_left']<SETTINGS['min_black_left'] or frame['blue_right']<SETTINGS['min_blue_right']:return False
    return any((frame['hash']^a['hash']).bit_count()<=SETTINGS['max_hash_distance'] and
        sum(abs(x-y) for x,y in zip(frame['rgb'],a['rgb']))/816<=SETTINGS['max_rgb_error'] for a in anchors)


def tail_start(rows,anchors):
    run=[]
    for frame in rows:
        if matches(frame,anchors):
            if run and abs(frame['time']-run[-1]-.5)>.01:run=[]
            run.append(frame['time'])
            if len(run)>=SETTINGS['min_run_frames']:return max(0,run[0]-.5)
        else:run=[]
    return None


def record_failure(project,result,description):
    root=project/'media/jev/script-first';slot=result['slot'];c=slot['top'];videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos']}
    doc=read(root/'creator-rejections.json');reference=slot['id']
    if not any(e.get('reference')==reference for e in doc['entries']):
        doc['entries'].append(dict(reference=reference,link_id=None,slot=slot['id'],output=result['output'],video_id=c['video_id'],source_group=c['source_group'],
            start=c['start'],end=videos[c['video_id']]['probe']['duration'],confirmed_shot=[c['start'],c['end']],timeline_seconds=slot['start_frame']/30,
            reason='Creator-confirmed channel outro',description=description,policy='Reported outro shot through source end; scan may establish an earlier boundary'))
        save_json(root/'creator-rejections.json',doc)


def scan(project,result,folder,status):
    videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
    c=result['slot']['top'];seed=videos[c['video_id']]
    if not seed.get('channel_id'):raise ValueError('Confirmed endcard source lacks channel identity')
    anchors=[r for r in samples(seed,math.floor(c['start']*2)/2,c['end']) if c['start']<=r['time']<c['end']]
    anchors=[r for r in anchors if r['black_left']>=SETTINGS['min_black_left'] and r['blue_right']>=SETTINGS['min_blue_right']]
    if len(anchors)<3:raise ValueError('Confirmed sample does not establish a persistent black-left, blue-right endcard')
    signature=digest([sha(Path(__file__)),SETTINGS,[(r['hash'],list(r['rgb'])) for r in anchors]])
    entries=[];reports=[];targets=[v for v in videos.values() if v.get('channel_id')==seed['channel_id']]
    for i,v in enumerate(sorted(targets,key=lambda v:v['id']),1):
        status(f"Check Movieclips ending {i}/{len(targets)}: {v['id']}")
        cache=folder/'scans'/(digest([signature,v['id'],Path(v['path']).stat().st_size,v.get('crop'),v['probe']['duration']])+'.json')
        if cache.exists():r=read(cache)
        else:
            duration=v['probe']['duration'];a=max(0,math.floor((duration-SETTINGS['tail_seconds'])*2)/2)
            rows=samples(v,a,duration);boundary=tail_start(rows,anchors)
            control_end=max(0,a-5);control_start=max(0,math.floor((control_end/2-10)*2)/2);control_end=min(control_end,control_start+SETTINGS['control_seconds'])
            controls=samples(v,control_start,control_end) if control_end>control_start else []
            r=dict(video_id=v['id'],source_duration=duration,outro_start=boundary,tail_samples=len(rows),control_samples=len(controls),
                control_matches=sum(matches(f,anchors) for f in controls),matched_tail_times=[f['time'] for f in rows if matches(f,anchors)])
            save_json(cache,r)
        reports.append(r)
        if r['outro_start'] is not None:entries.append(dict(video_id=v['id'],start=r['outro_start'],end=r['source_duration'],reason='Movieclips endcard matches creator-confirmed split black/blue template'))
    report=dict(version=1,settings=SETTINGS,seed_video_id=seed['id'],seed_range=[c['start'],c['end']],channel_id=seed['channel_id'],sources=reports,entries=entries,
        control_samples=sum(r['control_samples'] for r in reports),control_matches=sum(r['control_matches'] for r in reports))
    save_json(folder/'scan-report.json',report)
    if report['control_matches']:raise ValueError('Endcard template matched interior control samples; automatic exclusions require review')
    if seed['id'] not in {e['video_id'] for e in entries}:raise ValueError('Endcard scan failed to recover the confirmed source')
    save_json(project/'media/jev/script-first/outro-scans.json',report)
    return report,anchors,videos


def run(project):
    import msvcrt
    approve(project);root=project/'media/jev/script-first/stage5';refs=read(root/'references.json');state=read(root/'run.json')
    with (root/'test.lock').open('a+b') as lock:
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Another Stage 5 task is running') from exc
        folder=root/'outro-retry';folder.mkdir(exist_ok=True)
        for name in ['run.json','report.json']:
            target=folder/('before-'+name)
            if not target.exists():shutil.copy2(root/name,target)
        previous_summary=folder/'before-summary.md'
        if not previous_summary.exists():shutil.copy2(project/'production/jev-stage5-summary.md',previous_summary)
        original=Path(approve(project)['approved_script']).parent.parent
        protected=[Path(refs[k]) for k in ['edited_file','creator_reference','pre_edit']]+[original/n for n in ['project.json','links.json','script/script.md','visuals/visuals.md']]
        protected += [project/n for n in ['links.json','media/jev/candidates.json','media/jev/score-windows.json','media/jev/script-first/general-pools.json','media/jev/script-first/stage4/assignment.json']]
        before={str(p):sha(p) for p in protected};started=time.time();state.update(status='stage5_outro_check_running',pid=os.getpid(),task='outro-check',retry_comparison_ready=False);state.pop('error',None)
        def status(phase):
            if (root/'stop').exists():raise RuntimeError('Creator requested stop; completed quality scans retained')
            state.update(phase=phase,elapsed_seconds=time.time()-started);save_json(root/'run.json',state)
            lines=['# Stage 5 — short summary','',f"Status: **{state['status']}**. Phase: {phase}.",'',
                'The previous fill is rejected: the creator identified a Movieclips channel outro with black/logo on the left and blue waves on the right. The failed output is preserved.','',
                'Checking same-channel endings using the confirmed template; no VideoJev calls. Your edit and reference reviews remain protected. Stage 6 has not started.']
            if state.get('outro_scan'):lines+=['',f"Endcard scan: {state['outro_scan']['sources']} sources; {state['outro_scan']['detected']} tails excluded; {state['outro_scan']['control_samples']} interior control frames, {state['outro_scan']['control_matches']} template matches."]
            if state.get('quality_retries'):
                retry=state['quality_retries'][-1];lines+=['',f"Fill retry: {retry['status']}."+(f" New review: `{retry['output']}`." if retry.get('output') else ' '+retry.get('reason',''))]
            if state.get('comparison'):
                note='The new retry row will appear after rendering completes.'
                if state['retry_comparison_ready']:note='The third row is the new fill retry; the first row preserves the rejected attempt.'
                elif state['status']=='stage5_gate_incomplete':note='The retry was unfilled; the previous rows are preserved.'
                lines+=['',f"Comparison: `{state['comparison']}`. "+note]
            if state.get('error'):lines+=['','Error: '+state['error']]
            lines+=['','The new-query helicopter test remains unfilled. Stage 5 requires visual approval; nothing has been finalized.']
            (project/'production/jev-stage5-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(phase,flush=True)
        try:
            result=next(r for r in state['results'] if r['test']=='cached fill' and r['status']=='saved')
            status('Record the creator-confirmed failed replacement')
            record_failure(project,result,'Black left side with channel logo; right side has recognizable blue waves')
            report,anchors,videos=scan(project,result,folder,status)
            state['outro_scan']=dict(sources=len(report['sources']),detected=len(report['entries']),control_samples=report['control_samples'],control_matches=report['control_matches'])
            retry_path=folder/'retry-result.json'
            if retry_path.exists():retry=read(retry_path)
            else:
                status('Retry the 44:58 fill with the outro exclusions')
                retry=edit(project,Path(result['input']),'fill',result['at'],need=result['need'],status=status);retry['test']='cached fill retry'
            if retry['status']=='saved':
                c=retry['slot']['top'];ranges=creator_exclusions(project).get(c['video_id'],[])
                a=c['start']-c['leading_handle'];b=c['end']+c['trailing_handle']
                assert not any(lo<b and hi>a for lo,hi in ranges),'Retry handles cross a rejected source range'
                if videos[c['video_id']].get('channel_id')==report['channel_id']:
                    assert not any(matches(f,anchors) for f in samples(videos[c['video_id']],a,b)),'Retry still matches the rejected endcard'
                retry['outro_body_and_handles_checked']=True
            save_json(retry_path,retry)
            state['quality_retries']=[retry]
            review=read(root/'visual-review.json');review['cached fill'].update(verdict='rejected',note='Rejected: this replacement is a channel outro, with black/logo on the left and blue waves on the right.')
            if retry['status']=='saved':review['cached fill retry']=dict(verdict='pending',output=retry['output'],note='New replacement after the Movieclips outro scan. Awaiting your visual review.')
            save_json(root/'visual-review.json',review)
            status('Render the new comparison row')
            page,rows=comparison(project,refs,state['results']+state['quality_retries'],status)
            assert all(sha(p)==h for p,h in before.items()),'A protected project or saved score file changed'
            state.update(status='stage5_gate_incomplete',comparison=str(page),comparison_rows=rows,creator_visual_review=review,protected_inputs_unchanged=True,retry_comparison_ready=retry['status']=='saved')
            save_json(root/'report.json',state);status('Stopped before Stage 6; '+('review the third comparison row' if retry['status']=='saved' else 'no replacement passed the quality filters'))
        except Exception as exc:
            state.update(status='stage5_outro_check_failed',error=str(exc))
            try:status('Stopped; completed results retained')
            except RuntimeError:save_json(root/'run.json',state)
            raise
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',type=Path,required=True)
    run(parser.parse_args().project.resolve())
