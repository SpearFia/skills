# SPDX-License-Identifier: MIT OR Apache-2.0
"""Readback, decode and render checks without saving edits to the review."""
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filmcraft_rpc import FilmCraft
from stage3_sources import save_json,command
from stage4_assign import assert_no_overlap,FPS
from stage4_build import load,TICKS


def verify(project):
    folder=project/'media/jev';build=load(folder/'stage4-build.json');a=load(folder/'assignment.json')
    review=Path(build['review']);before=hashlib.sha256(review.read_bytes()).hexdigest()
    out=project/'production/jev-stage4';out.mkdir(exist_ok=True)
    assert_no_overlap(a['slots'])
    masters=load(folder/'masters.json')
    def streams(m):
        d=json.loads(command(['ffprobe','-v','error','-show_streams','-of','json',str(project/m['file'])],30))
        assert [s['codec_type'] for s in d['streams']]==['video'],m['file']
        assert d['streams'][0]['height']==480
    with ThreadPoolExecutor(max_workers=4) as e:list(e.map(streams,masters))
    seq=load(folder/'stage4-native-snapshot.json');tracks=build['tracks']
    by_id={c['clip']:c for t in seq['video'] for c in t['items']}
    items={c['item'] for s in a['slots'] if s['top'] for c in [by_id[s['top']['clip_id']]]}
    items.update(by_id[c['clip_id']]['item'] for s in a['slots'] for c in s['alternates'])
    assert not any(c['item'] in items for t in seq['audio'] for c in t['items'])
    toptrack=next(t for t in seq['video'] if t['id']==tracks['top'])
    for x,y in zip(toptrack['items'],toptrack['items'][1:]):assert x['endFrame']<=y['startFrame']
    clamps=[];quantization=[]
    for s in a['slots']:
        for c in ([s['top']] if s['top'] else [])+s['alternates']:
            native=by_id[c['clip_id']]
            assert native['durationFrames']==s['duration_frames']
            assert native['startFrame']==s['start_frame']
            error=abs(native['sourceIn']/TICKS-c['source_in'])
            assert error<=1/FPS+.000001,(s['id'],error)
            quantization.append(error)
            if min(c['leading_handle'],c['trailing_handle'])<2.49:clamps.append(dict(slot=s['id'],video=c['video_id'],leading=c['leading_handle'],trailing=c['trailing_handle']))
    higher=[t for t in seq['video'] if t['id'] not in tracks.values()]
    candidates=[s for s in a['slots'] if len(s['alternates'])==2 and len({c['video_id'] for c in [s['top']]+s['alternates']})==3]
    sample=next(s for s in candidates if not any(c['startFrame']<=s['start_frame']+15<c['endFrame'] for t in higher for c in t['items'] if 'Adjustment' not in c['name']))
    at=(sample['start_frame']+15)/FPS
    render_times={}
    with FilmCraft() as f:
        f.command('file.open',path=str(review))
        for label in ['top','alternate1','alternate2']:
            if label=='alternate1':f.command('edit.clear',clips=[sample['top']['clip_id']])
            if label=='alternate2':f.command('edit.clear',clips=[sample['alternates'][0]['clip_id']])
            start=time.perf_counter()
            r=f.command('file.exportFrame',path=str(out/(label+'.png')),format='png',target='program',time=round(at*TICKS))
            render_times[label]=time.perf_counter()-start
            print(label,r,flush=True)
    digests=[hashlib.sha256((out/(label+'.png')).read_bytes()).hexdigest() for label in render_times]
    assert len(set(digests))==3,'Deleting a clip did not reveal different footage'
    # Real-time UI playback is not exposed by the headless CLI. Measure a three-layer render separately.
    with FilmCraft() as f:
        f.command('file.open',path=str(review))
        start=time.perf_counter()
        result=f.command('file.exportMedia',path=str(out/'three-layer-480p.mp4'),format='h264',scale=480/2160,
            audio=False,range='custom',startSeconds=sample['start_frame']/FPS,
            endSeconds=(sample['start_frame']+sample['duration_frames'])/FPS,wait=True,hardwareEncoding='off')
        elapsed=time.perf_counter()-start
        print('EXPORT',result,flush=True)
    assert hashlib.sha256(review.read_bytes()).hexdigest()==before,'Verification changed review'
    report=dict(top_no_repeats=True,top_no_timeline_overlaps=True,master_count=len(masters),silent_video_only=True,
        handles_seconds=2.5,physical_source_clamps=clamps,source_in_max_rounding_seconds=max(quantization),
        ticks_per_second=TICKS,handle_ticks=round(2.5*TICKS),alternate_reveal_test=dict(slot=sample['id'],seconds=at,
        render_seconds=render_times,three_distinct_frames=True),
        render_benchmark=dict(content_seconds=sample['duration_frames']/FPS,wall_seconds=elapsed,
            export_result=result,interactive_playback_verified=False),review_unchanged_by_checks=True)
    save_json(folder/'stage4-verification.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    verify(p.parse_args().project.resolve())
