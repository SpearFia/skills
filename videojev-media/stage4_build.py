# SPDX-License-Identifier: MIT OR Apache-2.0
"""Link handled masters into the demo, push, then add native FilmCraft alternates."""
import argparse
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from filmcraft_rpc import FilmCraft
from stage4_assign import FPS,SPEARFIA,assert_no_overlap
from stage3_sources import command,pool,save_json

TICKS=254016000000
def ticks(frames):return frames*TICKS//FPS
def load(path):return json.loads(path.read_text(encoding='utf-8'))


def build(project):
    folder=project/'media/jev';a=load(folder/'assignment.json');inputs=load(folder/'input-cues.json')
    original=Path(inputs['source_project']).resolve()
    if project.resolve()==original:raise ValueError('Original project is read-only')
    assert_no_overlap(a['slots'])
    baseline={name:hashlib.sha256((original/name).read_bytes()).hexdigest()
              for name in ['project.json','links.json','script/script.md','visuals/visuals.md']}
    save_json(folder/'stage4-original-hashes.json',baseline)
    for name in ['title-sting.mp4','end-screen.mp4']:
        target=project/'B-roll'/name
        if not target.exists():shutil.copy2(original/'B-roll'/name,target)
    visuals=project/'visuals/visuals.md'
    def normalize_anchor(match):
        cue=json.loads(match[1])
        if cue.get('method')=='Generated artwork':cue['anchor']['quote']=pool.spoken_quote(cue['anchor']['quote'])
        return '<!-- visual-cue '+json.dumps(cue,ensure_ascii=False,separators=(',',':'))+' -->'
    if not (folder/'visuals-before-stage4.md').exists():shutil.copy2(visuals,folder/'visuals-before-stage4.md')
    visuals.write_text(re.sub(r'<!-- visual-cue (.*?) -->',normalize_anchor,visuals.read_text(encoding='utf-8')),encoding='utf-8')
    filled=[s for s in a['slots'] if s['top']]
    for s in filled:
        if not (project/s['top']['file']).is_file():raise ValueError('Master is missing')
    if not (folder/'stage4-links.json').exists():
        shutil.copy2(project/'links.json',folder/'links-before-stage4.json')
        os.environ['SPEARFIA_EXE']=SPEARFIA
        ids=pool.links_add(project,dict(links=[dict(line=s['line'],quote=s['quote'],media=s['top']['file'],
             **{'in':f"{s['top']['source_in']:.6f}"}) for s in filled]))
        if len(ids)!=len(filled):raise ValueError('links_add did not return every clip')
        save_json(folder/'stage4-links.json',dict(zip([s['id'] for s in filled],ids)))
    ids=load(folder/'stage4-links.json')
    actual_links={l['id']:l for l in pool.links(project)}
    if set(ids)!={s['id'] for s in filled}:raise ValueError('Assignment changed since linking; cached link map cannot be reused')
    for s in filled:
        if actual_links[ids[s['id']]]['media']['path']!=s['top']['file']:
            raise ValueError('Assignment source changed since linking')
        if abs(float(actual_links[ids[s['id']]].get('in','0'))-s['top']['source_in'])>.000001:
            raise ValueError('Assignment source-in changed since linking')
    if not (folder/'stage4-push.json').exists():
        old_plan=load(sorted((project/'sync/plans').glob('*.json'),key=lambda p:p.stat().st_mtime)[-1])
        save_json(folder/'assignment-timing.json',dict(vo_starts={i['source']['path']:i['start_frame']
            for i in old_plan['items'] if i['kind']=='clip' and i['track']=='A1'}))
        started=time.perf_counter()
        result=json.loads(command([SPEARFIA,'--project',str(project),'push','filmcraft','--json'],1800))
        save_json(folder/'stage4-push.json',result)
        save_json(folder/'stage4-push-timing.json',dict(seconds=time.perf_counter()-started))
    pushed=load(folder/'stage4-push.json')
    # The CLI's output schema is deliberately checked before touching any review.
    review=Path(pushed['review'])
    if not review.resolve().is_relative_to(project.resolve()):raise ValueError('Push escaped demo')
    target=review.with_name(review.stem+'-layers.fcproj')
    if target.exists():raise FileExistsError(target)
    plan=load(project/'sync/plans'/(review.stem.removeprefix('review-')+'.json'))
    new_vo={i['source']['path']:i['start_frame'] for i in plan['items'] if i['kind']=='clip' and i['track']=='A1'}
    timing=load(folder/'assignment-timing.json')
    deltas={path:new_vo[path]-start for path,start in timing['vo_starts'].items()}
    with FilmCraft() as f:
        f.command('file.open',path=str(review))
        seq=f.tool('sequence_inspect',{});top_track=seq['video'][1]['id'];alt2=seq['video'][0]['id']
        by_link={}
        for c in seq['video'][1]['items']:
            for s in filled:
                if c['name'].endswith('{#'+ids[s['id']]+'}'):by_link[s['id']]=c
        if len(by_link)!=len(filled):raise ValueError('Pushed clips do not match links')
        moves=[];extend=[]
        for s in filled:
            c=by_link[s['id']];delta=s['duration_frames']-c['durationFrames']
            if delta<0:f.command('timeline.trim',clip=c['clip'],edge='out',mode='regular',deltaFrames=delta)
            if delta>0:extend.append((c['clip'],delta))
            moves.append(dict(clip=c['clip'],track=top_track,time=ticks(s['start_frame']+deltas[s['vo_path']])))
            s['top']['clip_id']=c['clip']
        f.command('timeline.move',moves=moves,insert=False,linked=False)
        for clip,delta in extend:f.command('timeline.trim',clip=clip,edge='out',mode='regular',deltaFrames=delta)
        ids_set=set(ids.values())
        audio=[c['clip'] for track in seq['audio'] for c in track['items'] if any(c['name'].endswith('{#'+key+'}') for key in ids_set)]
        if audio:f.command('edit.clear',clips=audio)
        before={t['id'] for t in seq['video']}
        f.command('sequence.addTracks',video=1,videoAfter='first')
        seq=f.tool('sequence_inspect',{});added=[t for t in seq['video'] if t['id'] not in before]
        if len(added)!=1:raise ValueError('Alternate track was not inserted')
        alt2,alt1=[t['id'] for t in seq['video'][:2]]
        for tid,name in [(alt2,'Alternate 2'),(alt1,'Alternate 1'),(top_track,'Chosen footage')]:
            f.command('timeline.setTrack',track=tid,name=name)
        imported={}
        for s in filled:
            c=by_link[s['id']];imported[s['top']['file']]=c['item']
        for file in sorted({c['file'] for s in filled for c in s['alternates']} - imported.keys()):
            r=f.tool('media_import',dict(paths=[str(project/file)]))
            if r.get('errors') or len(r['items'])!=1:raise ValueError('Import failed: '+file)
            imported[file]=r['items'][0]
        alt_clips=[]
        for s in filled:
            for index,c in enumerate(s['alternates']):
                r=f.command('timeline.place',item=imported[c['file']],track=[alt1,alt2][index],
                    frame=s['start_frame']+deltas[s['vo_path']],sourceIn=round(c['source_in']*TICKS),
                    duration=ticks(s['duration_frames']),audio=False)
                if len(r['clips'])!=1:raise ValueError('Alternate placement failed')
                c['clip_id']=r['clips'][0];alt_clips.append(c['clip_id'])
                f.command('clip.rename',clip=c['clip_id'],name=f"ALT {index+1} {s['id']} {c['video_id']}")
        if alt_clips:
            f.command('timeline.select',clips=alt_clips,add=False,toggle=False)
            f.command('clip.scaleToFrameSize')
        f.command('edit.deselectAll')
        final=f.tool('sequence_inspect',{})
        track_by_id={t['id']:t for t in final['video']}
        for tid in [alt2,alt1,top_track]:
            for c in track_by_id[tid]['items']:
                if tid!=top_track or c['clip'] in [s['top']['clip_id'] for s in filled]:
                    expected=next((s for s in filled if c['clip'] in [s['top']['clip_id']]+[x['clip_id'] for x in s['alternates']]),None)
                    if expected is None:raise AssertionError('Unexpected footage clip')
                    assert c['startFrame']==expected['start_frame']+deltas[expected['vo_path']]
                    assert c['durationFrames']==expected['duration_frames']
        all_ids={s['top']['clip_id'] for s in filled}|set(alt_clips)
        assert not any(c['clip'] in all_ids for t in final['audio'] for c in t['items'])
        # shortcut: masked vertical Gaussian blur corrupts bottom-edge pixels in this CLI; use horizontal until the renderer is fixed.
        for t in final['video']:
            for c in t['items']:
                for index,effect in enumerate(c['effects']):
                    if effect['effect']=='gaussian_blur' and effect['masks']:
                        f.command('effects.setParam',clip=c['clip'],effect=index,param='dimensions',value=1)
        f.command('file.saveAs',path=str(target))
        save_json(folder/'stage4-native-snapshot.json',f.tool('sequence_inspect',{}))
    for name,h in baseline.items():
        if hashlib.sha256((original/name).read_bytes()).hexdigest()!=h:raise AssertionError('Original changed: '+name)
    save_json(folder/'assignment.json',a)
    result=dict(review=str(target),base_review=str(review),top_clips=len(filled),alternates=len(alt_clips),
        tracks=dict(top=top_track,alternate1=alt1,alternate2=alt2),vo_offset_changes=deltas,
        original_verified_unchanged=True,ticks_per_second=TICKS)
    save_json(folder/'stage4-build.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    build(p.parse_args().project.resolve())
