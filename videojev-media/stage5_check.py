# SPDX-License-Identifier: MIT OR Apache-2.0
"""Restore the pre-edit review and exercise Stage 5 only on saved copies."""
import copy
import html
import os
import shutil
import time
from pathlib import Path

from filmcraft_rpc import FilmCraft
from script_first import approve,read,sha
from stage3_index import subtract
from stage3_sources import save_json
from stage4_assign import FPS
from stage4_build import build_assignment
from stage5_edit import allocator,choose_exact,edit,footage_tracks,load_review,resolve_need,slot_at,source_spans,visible


def references(project,edited):
    approve(project);load_review(project,edited)
    folder=project/'media/jev/script-first/stage5';folder.mkdir(parents=True,exist_ok=True)
    manifest=folder/'references.json'
    if manifest.exists():
        refs=read(manifest)
        if Path(refs['edited_file']).resolve()!=edited.resolve():raise ValueError('Existing comparison uses a different edited review')
        if sha(refs['creator_reference'])!=refs['creator_sha256']:raise ValueError('Saved creator reference changed')
        return refs
    reference=edited.with_name(edited.stem+'-creator-reference.fcproj')
    data=edited.read_bytes()
    if reference.exists() and reference.read_bytes()!=data:raise FileExistsError(reference)
    if not reference.exists():reference.write_bytes(data)
    refs=dict(edited_file=str(edited),creator_reference=str(reference),creator_sha256=sha(reference),saved_at=time.time())
    save_json(manifest,refs);return refs


def restore(project,refs):
    root=project/'media/jev/script-first';folder=root/'stage5/restore';folder.mkdir(parents=True,exist_ok=True)
    original=root/'stage4';done=folder/'stage4-build.json'
    if not done.exists():
        for name in ['stage4-links.json','stage4-push.json','assignment-timing.json']:shutil.copy2(original/name,folder/name)
        links_before=sha(project/'links.json')
        build_assignment(project,folder,copy.deepcopy(read(original/'assignment.json')),Path(approve(project)['approved_script']).parent.parent)
        assert sha(project/'links.json')==links_before,'Restore changed demo links'
    restored=Path(read(done)['review'])
    expected=read(original/'stage4-native-snapshot.json');actual=read(folder/'stage4-native-snapshot.json')
    signature=lambda s:[(t['name'],[(c['clip'],c['item'],c['startFrame'],c['durationFrames'],c['sourceIn'],c['effects']) for c in t['items']]) for t in s['video']+s['audio']]
    assert signature(actual)==signature(expected),'Restoration differs from the pre-edit native snapshot'
    assert sha(refs['creator_reference'])==refs['creator_sha256']
    reference=project/'sync/review-plan-1793469563-pre-edit-reference.fcproj'
    if reference.exists() and sha(reference)!=sha(restored):raise ValueError('Pre-edit reference already exists with different content')
    if not reference.exists():shutil.copy2(restored,reference)
    refs.update(pre_edit=str(reference),pre_edit_sha256=sha(reference),restored_tracks=[dict(name=t['name'],clips=len(t['items'])) for t in actual['video']])
    save_json(root/'stage5/references.json',refs);return refs


def gaps(project,review):
    _,seq=load_review(project,review);occupied=[[a/254016000000,b/254016000000] for a,b,c in visible(footage_tracks(project,seq))]
    found=[]
    for s in read(project/'media/jev/script-first/stage4/assignment.json')['slots']:
        if s['kind']=='manual':continue
        for a,b in subtract(s['start_frame']/FPS,(s['start_frame']+s['duration_frames'])/FPS,occupied):
            start=round(a*FPS);end=min(round(b*FPS),start+120)
            if end-start>=45:found.append(dict(s,start_frame=start,duration_frames=end-start,top=None,alternates=[]))
    return sorted(found,key=lambda s:(s['kind']!='specific',s['start_frame']))


def comparison(project,refs,results,status):
    out=project/'production/jev-stage5';out.mkdir(exist_ok=True)
    rows=[]
    for index,r in enumerate(results):
        if r.get('status')!='saved':continue
        s=r['slot'];start=s['start_frame']/FPS;end=start+min(4,s['duration_frames']/FPS)
        files=[]
        for label,file in [('pre-edit',refs['pre_edit']),('creator',refs['creator_reference']),('stage5',r['output'])]:
            target=out/f'{index}-{label}.mp4';status('Render comparison '+target.name)
            if not target.exists():
                with FilmCraft() as f:
                    f.command('file.open',path=file)
                    export=f.command('file.exportMedia',path=str(target),format='h264',scale=480/2160,audio=False,range='custom',startSeconds=start,endSeconds=end,wait=True,hardwareEncoding='off')
                    assert export['offlineMedia']==[]
            files.append(target.name)
        rows.append(dict(mode=r['mode'],at=r['at'],input=r['input'],videos=files,new_query=r['new_query']))
    sections=[]
    for row in rows:
        sections.append('<h2>'+html.escape(row['mode']+' at '+row['at'])+'</h2><div class="row">'+''.join(
            '<figure><figcaption>'+label+'</figcaption><video controls preload="metadata" src="'+html.escape(file)+'"></video></figure>'
            for label,file in zip(['Original automatic review','Your saved edit','Stage 5 test'],row['videos']))+'</div>')
    (out/'comparison.html').write_text('<!doctype html><meta charset="utf-8"><title>Stage 5 comparison</title><style>body{font:16px system-ui;background:#151515;color:#eee;padding:24px}.row{display:flex;gap:12px}figure{margin:0;width:33%}video{width:100%}</style><h1>Stage 5 test copies</h1><p>All panels show the same timeline interval. Your saved edit and original project were preserved.</p>'+''.join(sections),encoding='utf8')
    return out/'comparison.html',rows


def run(project,edited):
    import msvcrt
    refs=references(project,edited);root=project/'media/jev/script-first/stage5';started=time.time()
    original=Path(approve(project)['approved_script']).parent.parent
    protected=[original/name for name in ['project.json','links.json','script/script.md','visuals/visuals.md']]
    protected += [project/name for name in ['links.json','media/jev/candidates.json','media/jev/score-windows.json','media/jev/script-first/stage4/assignment.json']]
    before={str(p):sha(p) for p in protected}
    with (root/'test.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Stage 5 tests are already running') from exc
        state=read(root/'run.json') if (root/'run.json').exists() else dict(results=[])
        if state.get('status')=='stage5_gate_ready':raise ValueError('Stage 5 test gate is already ready')
        if state.get('error'):save_json(root/'attempts'/(str(time.time_ns())+'.json'),state)
        state.pop('error',None)
        state.update(status='running',started=started,pid=os.getpid(),stage6_started=False)
        def status(phase):
            if (root/'stop').exists():raise RuntimeError('Creator requested stop; completed results retained')
            state.update(phase=phase,elapsed_seconds=time.time()-started);save_json(root/'run.json',state)
            lines=['# Stage 5 — short summary','',f"Status: **{state['status']}**. Phase: {phase}.",'',f"Elapsed: {state['elapsed_seconds']/60:.1f} min. Stage 6 has not started.",'',
                f"Your saved-edit reference: `{refs['creator_reference']}`."]
            if refs.get('pre_edit'):lines+=['',f"Reconstructed original: `{refs['pre_edit']}`. Native tracks, clip times, source offsets and effects match the saved pre-edit snapshot."]
            for result in state['results']:lines+=['',f"{result['test']}: {result['status']}"+(f" — `{result['output']}`" if result.get('output') else ': '+result.get('reason',''))]
            if state.get('comparison'):lines+=['',f"Comparison: `{state['comparison']}`."]
            if state.get('error'):lines+=['','Error: '+state['error'][:1200]]
            (project/'production/jev-stage5-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(phase,flush=True)
        try:
            status('Restore pre-edit layered review');refs=restore(project,refs)
            selected=None
            if not any(r['test']=='cached fill' and r['status']=='saved' for r in state['results']):
                for file in [Path(refs['pre_edit']),Path(refs['creator_reference'])]:
                    status('Find a representative saved-result gap in '+file.name);prepared=allocator(project,file,status);a=prepared[0]
                    for s in gaps(project,file):
                        candidate=choose_exact(a,s)
                        if candidate:s['selected_group']=candidate['source_group'];selected=(file,s,prepared);break
                    if selected:break
                if selected:
                    file,s,prepared=selected;need=s['question_id'] or s['selected_group'];at=f"{s['start_frame']/FPS:.6f}-{(s['start_frame']+s['duration_frames'])/FPS:.6f}"
                    result=edit(project,file,'fill',at,need=need,status=status,prepared=prepared);result.update(test='cached fill',need=need);state['results'].append(result)
                else:state['results'].append(dict(test='cached fill',status='unfilled',reason='No existing representative gap has enough unused saved matching evidence'))
                save_json(root/'run.json',state)
            if not any(r['test']=='new-query fill' for r in state['results']):
                cached=next((r for r in state['results'] if r['test']=='cached fill' and r['status']=='saved' and r['slot']['question_id']),None)
                if cached:
                    file=Path(cached['input']);s=cached['slot'];at=cached['at']
                else:
                    file=Path(refs['pre_edit']);s=next(s for s in gaps(project,file) if s['kind']=='specific');at=f"{s['start_frame']/FPS:.6f}-{(s['start_frame']+s['duration_frames'])/FPS:.6f}"
                a=allocator(project,file,status)[0];q=a.qs[s['question_id']];query='Visible scene: '+q['query']
                status('Test one new visual query: '+query)
                result=edit(project,file,'fill',at,query=query,group=q['source_group'],status=status);result.update(test='new-query fill',query=query)
                state['results'].append(result);save_json(root/'run.json',state)
            if not any(r['test']=='cached swap' for r in state['results']):
                file=Path(refs['pre_edit']);status('Test swapping a shot using saved evidence');prepared=allocator(project,file,status)
                result=dict(status='unfilled',reason='No unused replacement was available')
                for s in read(project/'media/jev/script-first/stage4/assignment.json')['slots']:
                    if not s['top'] or not s['alternates']:continue
                    result=edit(project,file,'swap',str((s['start_frame']+.5)/FPS),need=s['question_id'] or s['groups'][0],prepared=prepared,status=status)
                    if result['status']=='saved':break
                result['test']='cached swap';state['results'].append(result);save_json(root/'run.json',state)
            status('Build comparison page');page,rows=comparison(project,refs,state['results'],status);state['comparison']=str(page)
            assert sha(refs['creator_reference'])==refs['creator_sha256'],'Saved edit reference changed'
            assert sha(refs['pre_edit'])==refs['pre_edit_sha256'],'Reconstructed original changed'
            assert all(sha(p)==h for p,h in before.items()),'A protected project or search input changed'
            state.update(status='stage5_gate_ready' if len(state['results'])==3 and all(r['status']=='saved' for r in state['results']) else 'stage5_gate_incomplete',
                creator_reference_unchanged=True,pre_edit_reference_unchanged=True,original_project_unchanged=True,comparison_rows=rows)
            save_json(root/'report.json',state);status('Stopped before Stage 6')
        except Exception as exc:
            state.update(status='stage5_failed',error=str(exc))
            try:status('Stopped; completed results preserved')
            except RuntimeError:save_json(root/'run.json',state)
            raise
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
