# SPDX-License-Identifier: MIT OR Apache-2.0
"""Prepare and review edits against a saved native timeline without rewriting it."""
import copy
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import urllib.request
import uuid
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

from script_first import approve, creator_exclusions, read,key as question_key
from stage3_sources import save_json
from stage5_edit import footage_tracks, load_review, master_map, visible
from filmcraft_rpc import FilmCraft
from editing_policy import MOTIONS,DEPLOYMENT_ENABLED,require_deployment,require_short_native

TICKS = 254016000000
MODEL = 'Cloudflare/clef-flash'
REVISION = 'fb4417d31c1d0f9e7e77f1141b40aaede7491e00'
CLI = r'C:\Program Files\FilmCraft\filmcraft-cli.exe'
RENDERER = Path(r'C:\dev\spearfia\spearfia\tools\editing-pilot')
CRITERIA = ('Choose a supplied complete treatment only when its labels, reveal order and provenance agree with the approved narration and visual intent. '
            'Preserve qualifiers, existing captions and sound. Keep current presentation when it already serves the beat. '
            'Choose none-of-these when safe judgment requires missing intent or evidence. Scores are observations, not independently verified facts.')


@contextmanager
def exclusive(folder):
    import msvcrt
    with (folder/'editing.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Another editing operation owns this review folder') from exc
        try:yield
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def native_read(path):
    data=read(path)
    if data.get('format')!='filmcraft.project': raise ValueError('Expected a native FilmCraft project')
    sequences=[v['kind']['Sequence'] for v in data['project']['items'].values() if 'Sequence' in v['kind']]
    if len(sequences)!=1: raise ValueError('Expected exactly one native sequence')
    return data,sequences[0]


def native_matches(expected,actual,anchors):
    normalized=copy.deepcopy(expected)
    clips={c['id']:c for t in actual['video_tracks'] for c in t['items']}
    for track in normalized['video_tracks']:
        for clip in track['items']:
            other=clips.get(clip['id'])
            if other is None:return False
            if len(clip['effects'])!=len(other['effects']):return False
            for effect,observed in zip(clip['effects'],other['effects']):
                if effect['effect']!=observed['effect']:return False
                param='anchor' if effect['effect']=='motion' and clip['id'] in anchors else 'position' if effect['effect']=='graphic_text' else None
                if param is None:continue
                a=effect['params'][param]['value']['Vec2'];b=observed['params'][param]['value']['Vec2']
                # FilmCraft can shift the last decimal of a pixel coordinate on JSON round trip.
                if any(not math.isfinite(a[k]) or not math.isfinite(b[k]) or abs(a[k]-b[k])>1e-9 for k in ['x','y']):return False
                a.update(b)
    return normalized==actual


def overlap(a, b):
    return a['start'] < b['end'] and b['start'] < a['end']


def reveal_anchors(text,labels,words,heard,origin,fps,word_fps,interval):
    actions=dict(re.findall(r'Reveal "([^"]+)" at "([^"]+)"',text))
    normal=lambda t:re.sub(r'[^a-z0-9]','',t.casefold())
    tokens=[normal(w['text']) for w in words];frames=[]
    for label in labels:
        if label not in actions: return None
        quote=[normal(w) for w in actions[label].split()]
        matches=[i for i in range(len(tokens)-len(quote)+1) if tokens[i:i+len(quote)]==quote]
        if len(matches)!=1: return None
        w=words[matches[0]];seconds=w['startFrame']/word_fps
        if not any(normal(h[0])==tokens[matches[0]] and abs(h[1]-seconds)<=2/fps for h in heard): return None
        frame=origin+round(seconds*fps)
        if not interval['start']<=frame<interval['end']-18: return None
        frames.append(frame)
    return frames if frames==sorted(frames) else None


def supported(clip):
    if not math.isfinite(clip['speed']) or clip['speed'] <= 0 or clip.get('reverse') or clip.get('frame_hold') is not None:
        return False
    for e in clip.get('effects', []):
        p = e.get('params', {}).get('speed', {})
        if e['effect'] == 'time_remap' and e.get('enabled', True) and (p.get('keyframes') or p.get('value', {}).get('Float', 100) != 100):
            return False
    return True


def assess(packet, response, question_id='treatment'):
    if not isinstance(response,dict) or response.get('model') != MODEL:
        raise ValueError('Wrong decision model')
    answers = response.get('answers')
    answer = answers.get(question_id) if isinstance(answers,dict) else None
    ps = answer.get('probabilities') if isinstance(answer,dict) else None
    if not isinstance(ps,dict) or answer.get('type') != 'choice' or set(ps) != set(packet['options']) or len(ps)<2:
        raise ValueError('Incomplete decision options')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in ps.values()) or abs(sum(ps.values())-1) > .001:
        raise ValueError('Invalid probability distribution')
    ranked = sorted(ps, key=ps.get, reverse=True)
    if answer.get('choice') != ranked[0]:
        raise ValueError('Choice contradicts distribution')
    threshold = ranked[0] != 'none-of-these' and ps[ranked[0]] >= .95 and ps[ranked[0]]-ps[ranked[1]] >= .20
    return dict(choice=ranked[0], probabilities=ps, threshold_pass=threshold,
                evidence_adequate=packet['evidence_adequate'], eligible=threshold and packet['evidence_adequate'] and not packet['flags'])


def calibration_gate(records, labels, criteria_hash):
    if labels.get('criteria_sha256') != criteria_hash:
        return dict(passed=False, reason='Creator labels and frozen criteria are required')
    rows = labels.get('labels', [])
    ids = [x['id'] for x in rows]
    if len(ids) != len(set(ids)) or not any(x.get('split') == 'calibration' for x in rows):
        raise ValueError('Calibration and held-out examples must be distinct')
    for row in rows:
        if row.get('split')=='calibration':
            r=records.get(row['id'])
            if not r or row.get('context_sha256')!=r['context_sha256'] or not isinstance(row.get('choice'),str) or type(row.get('supported')) is not bool:
                return dict(passed=False,reason='Complete creator-labeled calibration examples are required')
    held = []
    for row in rows:
        if row.get('split') != 'held-out':
            continue
        r = records.get(row['id'])
        if not r or row.get('context_sha256') != r['context_sha256']:
            raise ValueError('Creator label refers to a stale decision')
        if r['assessment']['eligible']:
            held.append((r['assessment']['choice'] == row['choice'], row.get('supported') is True))
    agreement = sum(x for x, _ in held)/len(held) if held else 0
    unsupported = sum(not x for _, x in held)
    return dict(passed=len(held) >= 20 and agreement >= .95 and unsupported == 0,
                eligible_held_out=len(held), agreement=agreement, unsupported_evidence_errors=unsupported,
                scope='Pilot agreement only; not a general accuracy guarantee')


def attach_evidence(source, question_ids, choices):
    """Only whole-window observations from the exact source and question are relevant."""
    if source.get('flags'):
        return []
    interval = source['source_interval']
    lo, hi = interval['start']/TICKS, interval['end']/TICKS
    return [r for r in choices if r.get('video_id') == source['lineage']['source_id'] and r.get('question_id') in question_ids
            and r['start'] <= lo+1e-6 and r['end'] >= hi-1e-6]


def prepare(project, review, out, section='Star 4'):
    project, review, out = project.resolve(), review.resolve(), out.resolve()
    if out.exists() or out.is_relative_to(project) or any((p/'.git').exists() for p in [out, *out.parents]):
        raise ValueError('Use a fresh output outside the project and Git')
    require_short_native(native_read(review)[1],project)
    if not (project/'media/jev/script-first/approval.json').is_file():
        raise ValueError('Editing studies require existing creator-approved beats; preparation cannot create approval')
    document = approve(project)
    data, seq = load_review(project, review)
    fps = Fraction(seq['settings']['frame_rate']['num'], seq['settings']['frame_rate']['den'])
    frame_ticks = Fraction(TICKS, fps)
    to_frame = lambda ticks: round(Fraction(ticks)/frame_ticks)
    beats = [b for b in document['beats'] if b['section'].startswith(section+' ') or b['section'] == section]
    if not beats:
        raise ValueError('No approved beats for section')
    timings = read(project/'media/jev/script-first/stage4/beat-times.json')
    starts = read(project/'media/jev/script-first/stage4/assignment-timing.json')['vo_starts']
    paths = {timings[b['id']]['vo_path'] for b in beats}
    if len(paths) != 1:
        raise ValueError('Section must have one approved narration asset')
    vo_path = paths.pop()
    items = data['project']['items']
    voices = [c for t in seq['audio_tracks'] for c in t['items'] if c['enabled'] and
              Path(items[str(c['item'])]['kind'].get('Media', {}).get('media', {}).get('File', {}).get('path', '')).resolve() == (project/vo_path).resolve()]
    if len(voices) != 1 or not supported(voices[0]) or voices[0]['speed'] != 1 or voices[0]['source_in'] != 0:
        raise ValueError('Narration needs explicit timing review')
    vo = voices[0]; start, end = to_frame(vo['start']), to_frame(vo['start']+vo['duration'])
    offset = start-starts[vo_path]
    heard = read(project/'media/vo-words.json')[vo_path]
    if heard['sha256'] != file_hash(project/vo_path):
        raise ValueError('Stale approved narration observations')
    protected = [review, project/'project.json', project/'links.json', project/'script/script.md', project/'visuals/visuals.md', project/'channel.md',
                 project/'media/jev/script-first/beats.json', project/'media/jev/script-first/approval.json', project/'media/jev/script-first/stage6/stop']
    original = Path(document['approved_script']).parent.parent
    protected += [original/n for n in ['project.json', 'links.json', 'script/script.md', 'visuals/visuals.md']]
    protected += list((project/'sync').glob('*.fcproj'))+list((project/'sync').glob('approved-*'))+list((original/'sync').glob('approved-*'))
    protected += list((project/'media/jev/script-first/stage6').glob('**/*.json'))
    inputs = {str(p): file_hash(p) for p in dict.fromkeys(protected) if p.is_file()}
    sources, bindings = [], [];media_hashes={}
    masters = master_map(project)
    excluded = creator_exclusions(project)
    for a, b, c in visible(footage_tracks(project, seq)):
        if a >= vo['start']+vo['duration'] or b <= vo['start']:
            continue
        path = Path(items[str(c['item'])]['kind']['Media']['media']['File']['path'])
        m = masters.get(str(path.resolve()).casefold())
        flags = []
        if m is None:
            flags.append('unmapped-source-lineage')
        if not supported(c):
            flags.append('unsupported-retiming')
        lo, hi = max(a, vo['start']), min(b, vo['start']+vo['duration'])
        speed=c['speed'] if math.isfinite(c['speed']) and c['speed']>0 else 1
        source_in = c['source_in']+round((lo-c['start'])*speed)
        source_end = source_in+round((hi-lo)*speed)
        origin = round(m['start']*TICKS) if m else 0
        if m and any(x < (origin+source_end)/TICKS and y > (origin+source_in)/TICKS for x, y in excluded.get(m['video_id'], [])):
            flags.append('creator-exclusion-conflict')
        sid = 'clip-'+str(c['id'])
        if str(path) not in media_hashes: media_hashes[str(path)]=file_hash(path)
        sources.append(dict(id=sid, lineage=dict(source_id=m['video_id'] if m else str(path), selected_clip_id=str(c['id'])),
            source_interval=dict(start=origin+source_in, end=origin+source_end, timebase=dict(num=TICKS, den=1)),
            timeline_interval=dict(start=to_frame(lo), end=to_frame(hi)), speed=c['speed'], crop=m.get('crop') if m else None,
            master=m, native_clip=copy.deepcopy(c), native_item=c['item'], flags=flags,reviewed_proxy_sha256=media_hashes[str(path)]))
        info=items[str(c['item'])]['kind']['Media']['info']['video']
        bindings.append(dict(source_id=sid, quality='proxy', path=str(path), sha256=media_hashes[str(path)], width=info['width'], height=info['height']))
    visuals=[]
    for block in re.split(r'(?=<!-- visual-cue )', (project/'visuals/visuals.md').read_text(encoding='utf-8'))[1:]:
        meta, body = block.split(' -->', 1)
        cue=json.loads(meta[len('<!-- visual-cue '):]);cue['direction']=body.split('\n## ')[0].strip();visuals.append(cue)
    choices=[]
    for path in [project/'media/jev/script-first/query-results/cached-choices.json', project/'media/jev/script-first/query-results/candidates.json']:
        if path.exists():
            choices += read(path)
    channel=(project/'channel.md').read_text(encoding='utf-8')
    channel_criteria='\n\n'.join(m.group(0) for m in re.finditer(r'^## (?:Editing|Sound|Non-negotiables|Never does)\n.*?(?=^## |\Z)', channel, re.M|re.S))
    videojev=read(Path(__file__).with_name('config.json'))
    criteria_hash=digest(dict(criteria=CRITERIA, channel=channel_criteria, threshold=[.95,.20]))
    edits=[];windows=[];aligned=None
    for index, beat in enumerate(beats):
        t=timings[beat['id']]; interval=dict(start=max(start,t['start_frame']+offset), end=min(end,t['end_frame']+offset))
        if interval['end'] <= interval['start']:
            raise ValueError('Invalid narration interval')
        relevant=[s for s in sources if overlap(s['timeline_interval'],interval)]
        plans=[v for v in visuals if v['anchor']['line'] <= beat['line']-1 < v['anchor']['line']+v['anchor']['lines']]
        text='\n'.join(v['direction'] for v in plans)
        labels=list(dict.fromkeys(re.findall(r'^TEXT: (.+)$',text,re.M)))
        flags=list(dict.fromkeys(f for s in relevant for f in s['flags']))
        if not relevant: flags.append('no-selected-picture')
        reveals=None
        if re.search(r'^ACTION:',text,re.M):
            if aligned is None:
                result=subprocess.run(['cargo','run','--quiet','--release','-p','spearfia-sync','--example','editing_words','--',str(original),vo_path],
                    cwd=RENDERER.parent.parent,check=True,capture_output=True,text=True,timeout=600)
                aligned=json.loads(result.stdout)
            reveals=reveal_anchors(text,labels,aligned['words'],heard['words'],start,float(fps),aligned['fps'],interval)
        if reveals is None: flags.append('missing-explicit-reveal-anchors')
        qids={question_key(v['source_group'],v['query']) for v in beat['visuals'] if v.get('query')}
        evidence=[r for s in relevant for r in attach_evidence(s,qids,choices)]
        adequate=beat['classification']=='general' or bool(relevant) and all(any(r.get('scene_confirmed') is True and
            r.get('reviewed_input_sha256')==s['reviewed_proxy_sha256'] and r.get('crop')==s['crop'] for r in attach_evidence(s,qids,choices)) for s in relevant)
        if not adequate: flags.append('unreviewed-or-missing-visual-evidence')
        occupied=[c for t in seq['video_tracks'] if t['id'] not in {t['id'] for t in footage_tracks(project,seq)} for c in t['items']
                  if c['enabled'] and c['start'] < interval['end']*frame_ticks and c['start']+c['duration'] > interval['start']*frame_ticks]
        generated=[c for c in occupied if any(v['id'] in c['name'] for v in plans)]
        manual=[c for c in occupied if c not in generated]
        if manual: flags.append('manual-effect-or-overlay-conflict')
        candidates=[]
        if labels and len(labels)<=4 and all(len(x)<=65 for x in labels) and (interval['end']-interval['start'])/float(fps)>=max(2, sum(map(len,labels))/15):
            for kind in ['progressive','comparison','source-card']:
                if kind=='comparison' and len(labels)!=2: continue
                if kind=='source-card' and len(labels)<2: continue
                for motion in MOTIONS:
                    candidates.append(dict(id=kind+'-'+motion,kind=kind,labels=labels,layout='caption-band-reserved',motion=motion,caption_style='existing-native',
                        sounds=[],source_ids=[s['id'] for s in relevant],reveal_frames=reveals or [interval['start']]*len(labels),replace_generated_cards=[str(c['id']) for c in generated]))
        if not candidates: flags.append('no-complete-supplied-treatment')
        native_captions=[dict(track=t['id'],style=t['style'],caption=c) for t in seq['caption_tracks'] for c in t['captions']
            if c['start']<interval['end']*frame_ticks and c['start']+c['duration']>interval['start']*frame_ticks]
        native_sounds=[c for t in seq['audio_tracks'] for c in t['items'] if c['start']<interval['end']*frame_ticks and c['start']+c['duration']>interval['start']*frame_ticks]
        packet=dict(id=beat['id'],narration=beat['text'],narration_sha256=heard['sha256'],neighbors=[b['text'] for j,b in enumerate(beats) if abs(j-index)==1],
            native_captions=native_captions,native_sounds=native_sounds,native_overlays=occupied,
            intent=plans,source_ids=[s['id'] for s in relevant],footage=[s for s in relevant],evidence=evidence,evidence_adequate=adequate,
            evidence_contract=dict(model=videojev['model'],context=32768,review_status='Original result status retained; score is not factual verification'),
            candidates=candidates,options=['keep',*[c['id'] for c in candidates],'none-of-these'],flags=flags,evidence_questions=beat['visuals'],
            criteria=CRITERIA,channel_criteria=channel_criteria,criteria_sha256=criteria_hash,model_revision=REVISION)
        context_hash=digest(packet);packet['context_sha256']=context_hash;windows.append(packet)
        caption_refs=[str(c['id']) for t in seq['caption_tracks'] for c in t['captions'] if c['start']<interval['end']*frame_ticks and c['start']+c['duration']>interval['start']*frame_ticks]
        edits.append(dict(id=beat['id'],interval=interval,source_ids=[s['id'] for s in relevant],narration_anchors=[dict(word_id=beat['id']+'-start',frame=interval['start'])],
            treatment=dict(kind='keep',parameters={}),captions=caption_refs,sounds=[],decision=dict(context_sha256=context_hash,status='pending')))
    out.mkdir(parents=True);shutil.copy2(review,out/'input.fcproj')
    recipe=dict(version=1,reviewed_input_sha256=file_hash(review),timebase=dict(num=fps.numerator,den=fps.denominator),
        canvas=dict(width=seq['settings']['width'],height=seq['settings']['height']),section=dict(start=start,end=end),sources=sources,edits=edits,media_bindings=bindings,
        project=str(project),inputs=inputs,windows=windows,criteria_sha256=criteria_hash,dependencies=[],section_name=section)
    save_json(out/'editing-recipe.json',recipe)
    save_json(out/'prepared.json',dict(recipe_sha256=file_hash(out/'editing-recipe.json')))
    save_json(out/'calibration-labels.template.json',dict(criteria_sha256=criteria_hash,labels=[dict(id=p['id'],context_sha256=p['context_sha256'],
        split='calibration' if i<10 else 'held-out',choice=None,supported=None) for i,p in enumerate(windows)]))
    return recipe


def validate_inputs(recipe, folder):
    if (folder/'prepared.json').exists() and file_hash(folder/'editing-recipe.json')!=read(folder/'prepared.json')['recipe_sha256']:
        raise ValueError('Prepared recipe changed; prepare a new snapshot')
    if file_hash(folder/'input.fcproj') != recipe['reviewed_input_sha256']:
        raise ValueError('Reviewed native snapshot changed')
    for name, expected in recipe['inputs'].items():
        if not Path(name).is_file() or file_hash(name) != expected:
            raise ValueError('Reviewed input changed: '+name)
    for binding in recipe['media_bindings']:
        if not Path(binding['path']).is_file() or file_hash(binding['path']) != binding['sha256']:
            raise ValueError('Media binding changed')
        source=next((s for s in recipe.get('sources',[]) if s['id']==binding['source_id']),None)
        if source is None:raise ValueError('Binding has no source lineage')
        if binding['quality']=='proxy' and source.get('reviewed_proxy_sha256',binding['sha256'])!=binding['sha256']:
            raise ValueError('Editorial source fingerprint changed')
    for p in recipe['windows']:
        if digest({k:v for k,v in p.items() if k!='context_sha256'}) != p['context_sha256']:
            raise ValueError('Decision context changed')


def decisions(folder,packets):
    cache=folder/'decisions';cache.mkdir(exist_ok=True);records={};calls=0
    for p in packets:
        key=p['context_sha256'];path=cache/(key+'.json')
        if path.exists():
            record=read(path)
            if record['context_sha256']!=key or record['revision']!=REVISION: raise ValueError('Stale decision cache')
            if 'response' in record: record['assessment']=assess(p,record['response'])
        elif not p['candidates']:
            record=dict(context_sha256=key,revision=REVISION,assessment=dict(choice='keep',eligible=False),review_flags=p['flags'])
        else:
            request=dict(model=MODEL,state=p,questions=dict(treatment=dict(type='choice',instructions=CRITERIA,
                criteria={o:('Preserve current footage, native effects, captions and audio' if o=='keep' else 'Abstain' if o=='none-of-these' else json.dumps(next(c for c in p['candidates'] if c['id']==o))) for o in p['options']})))
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8008/v1/systemone',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'}),timeout=180) as response:
                    result=json.load(response)
                calls+=1;record=dict(context_sha256=key,revision=REVISION,response=result,assessment=assess(p,result))
            except Exception as exc:
                record=dict(context_sha256=key,revision=REVISION,assessment=dict(choice='keep',eligible=False),error=str(exc))
        # Persist successful and deterministic results. Worker failures are retryable.
        if 'error' not in record: save_json(path,record)
        records[p['id']]=record
    return records,calls


def preview(folder, render=True):
    require_short_native(native_read(folder/'input.fcproj')[1],read(folder/'editing-recipe.json')['project'])
    with exclusive(folder):
        return _preview(folder,render)


def _preview(folder, render=True):
    from contextlib import nullcontext
    from editing_workers import gather,ClefSession
    folder=folder.resolve();recipe=read(folder/'editing-recipe.json')
    validate_inputs(recipe,folder)
    evidence=gather(folder,recipe)
    packets=copy.deepcopy(recipe['windows'])
    for p in packets:
        observations=[o for o in evidence['observations'].values() if any(o['input']['path']==b['path'] for b in recipe['media_bindings'] if b['source_id'] in p['source_ids'])]
        if observations:
            p['additional_evidence']=observations
            p['context_sha256']=digest({k:v for k,v in p.items() if k!='context_sha256'})
    save_json(folder/'decision-contexts.json',packets)
    missing=any(p['candidates'] and not (folder/'decisions'/(p['context_sha256']+'.json')).exists() for p in packets)
    try:
        with ClefSession(folder,uuid.uuid4().hex) if missing else nullcontext():
            records,calls=decisions(folder,packets)
    except (OSError,RuntimeError,TimeoutError) as exc:
        records={p['id']:dict(context_sha256=p['context_sha256'],revision=REVISION,assessment=dict(choice='keep',eligible=False),error=str(exc)) for p in packets};calls=0
    labels=read(folder/'calibration-labels.json') if (folder/'calibration-labels.json').exists() else {}
    gate=calibration_gate(records,labels,recipe['criteria_sha256'])
    # Creator has disabled deployment independently of the statistical pilot gate.
    draft=folder/'review.fcproj'
    previous=read(folder/'preview-report.json') if (folder/'preview-report.json').exists() else {}
    if draft.exists() and file_hash(draft)!=previous.get('draft_sha256',recipe['reviewed_input_sha256']):
        raise ValueError('Existing review was modified; preserve it and prepare a new snapshot')
    application_key=digest(dict(gate=gate,decisions=records,recipe=file_hash(folder/'editing-recipe.json')))
    dependencies=[]
    if DEPLOYMENT_ENABLED and gate['passed'] and previous.get('application_key')==application_key:
        dependencies=previous['dependencies']
        for dep in dependencies:
            if file_hash(dep['path'])!=dep['render_sha256']: raise ValueError('Applied insert changed')
    elif DEPLOYMENT_ENABLED and gate['passed']:
        dependencies=apply_decisions(folder,recipe,records,draft)
    elif not draft.exists(): shutil.copy2(folder/'input.fcproj',draft)
    result=dict(model_calls=calls,gate=gate,decisions=records,draft=str(draft),draft_sha256=file_hash(draft),application_key=application_key,applied=len(dependencies),dependencies=dependencies,
        pending='Creator has disabled deployment; short studies and recommendations only')
    save_json(folder/'preview-report.json',result)
    write_report(folder,recipe,result)
    if render:
        output=folder/'star4-preview-540p.mp4';stamp=folder/'render.json'
        identity=digest(dict(native=file_hash(draft),section=recipe['section'],scale=540/recipe['canvas']['height']))
        if output.exists():
            if not stamp.exists() or read(stamp).get('identity')!=identity or read(stamp).get('sha256')!=file_hash(output):
                raise ValueError('Unverified existing render')
        else:
            fps=recipe['timebase']['num']/recipe['timebase']['den']
            command=[CLI,'--compact','--project',str(draft),'export',str(output),'--format','h264','--start',str(recipe['section']['start']/fps),
                '--end',str(recipe['section']['end']/fps),'--scale',str(540/recipe['canvas']['height'])]
            with (folder/'render.log').open('w',encoding='utf8') as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=7200)
            info=inspect_media(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
            expected=recipe['section']['end']-recipe['section']['start']
            if video['height']!=540 or int(video['nb_frames'])!=expected or not any(s['codec_type']=='audio' for s in info['streams']):
                raise ValueError('Full section preview failed resolution, exact duration or audio checks')
            save_json(stamp,dict(identity=identity,sha256=file_hash(output),frames=expected,width=video['width'],height=video['height'],audio=True))
        info=inspect_media(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
        if video['height']!=540 or int(video['nb_frames'])!=recipe['section']['end']-recipe['section']['start'] or not any(s['codec_type']=='audio' for s in info['streams']):
            raise ValueError('Cached preview failed complete-section media checks')
        save_json(folder/'preview-media-check.json',dict(width=video['width'],height=video['height'],frames=int(video['nb_frames']),audio=True))
        from calibration_examples import generate
        generate(folder)
        write_report(folder,recipe,result)
    validate_inputs(recipe,folder)
    return result


def inspect_media(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True,timeout=60)
    return json.loads(result.stdout)


def render_insert(folder,recipe,edit,candidate,native,quality):
    sources=[s for s in recipe['sources'] if s['id'] in candidate['source_ids']]
    bindings=[b for b in recipe['media_bindings'] if b['source_id'] in candidate['source_ids']]
    if not sources or len(bindings)!=len(sources) or quality=='hq' and any(b['quality']!='hq' for b in bindings):
        raise ValueError('Every baked insert dependency needs a verified resolution binding')
    code={str(p.relative_to(RENDERER)):file_hash(p) for p in (RENDERER/'src').glob('*.ts*')}
    code['package-lock.json']=file_hash(RENDERER/'package-lock.json')
    code['editing_recipe.py']=file_hash(Path(__file__))
    identity=digest(dict(native=file_hash(native),edit=edit,candidate=candidate,bindings=bindings,quality=quality,code=code))
    work=folder/'renders'/identity;receipt=work/'verified.json';output=work/'insert.mp4'
    if receipt.exists():
        r=read(receipt)
        if file_hash(output)!=r['render_sha256']: raise ValueError('Rendered insert changed')
        return r
    if work.exists(): raise ValueError('Partial insert render exists; retain it for diagnosis before retry')
    work.mkdir(parents=True);assets=work/'assets';assets.mkdir()
    background=work/'background.fcproj'
    with FilmCraft() as f:
        f.command('file.open',path=str(native))
        _,seq=native_read(native)
        replace=set(map(int,candidate['replace_generated_cards']))
        enabled=[c['id'] for t in seq['video_tracks'] for c in t['items'] if c['id'] in replace and c['enabled']]
        if enabled:f.command('clip.enable',clips=enabled)
        for i,t in enumerate(seq['caption_tracks'],1):
            if t.get('enabled',True): f.command('captions.setTrack',track='C'+str(i),enabled=False)
        f.command('file.saveAs',path=str(background))
    fps=recipe['timebase']['num']/recipe['timebase']['den'];height=1080 if quality=='hq' else 540
    a,b=edit['interval']['start'],edit['interval']['end']
    subprocess.run([CLI,'--compact','--project',str(background),'export',str(assets/'background.mp4'),'--format','h264','--start',str(a/fps),'--end',str(b/fps),
                    '--scale',str(height/recipe['canvas']['height']),'--no-audio'],check=True,capture_output=True,timeout=1800)
    props=dict(**recipe['canvas'],fps=fps,duration=b-a,background='background.mp4',kind=candidate['kind'],labels=candidate['labels'],motion=candidate['motion'],
        reveals=[f-a for f in candidate['reveal_frames']])
    if candidate.get('source_label'):props['sourceLabel']=candidate['source_label']
    if candidate.get('qualifier'):props['qualifier']=candidate['qualifier']
    save_json(work/'props.json',props)
    subprocess.run(['node',str(RENDERER/'node_modules/@remotion/cli/remotion-cli.js'),'render',str(RENDERER/'src/recipe-index.tsx'),'RecipeInsert',str(output),
        '--props',str(work/'props.json'),'--public-dir',str(assets),'--codec','h264','--scale',str(height/recipe['canvas']['height']),'--concurrency','2','--log','error'],check=True,cwd=RENDERER,timeout=1800)
    info=inspect_media(output);v=next(s for s in info['streams'] if s['codec_type']=='video')
    if int(v['nb_frames'])!=b-a or v['height']!=height or any(s['codec_type']=='audio' for s in info['streams']):
        raise ValueError('Insert timing, resolution or streams differ')
    result=dict(edit_id=edit['id'],source_ids=candidate['source_ids'],render_sha256=file_hash(output),path=str(output),quality=quality,
                bindings=bindings,interval=edit['interval'],candidate=candidate,frames=b-a)
    save_json(receipt,result);return result


def apply_decisions(folder,recipe,records,target,quality='proxy',native=None):
    require_deployment()
    native=native or folder/'input.fcproj';selected=[]
    for edit,p in zip(recipe['edits'],recipe['windows']):
        assessment=records[p['id']]['assessment']
        if assessment['eligible'] and assessment['choice'] not in {'keep','none-of-these'}:
            candidate=next(c for c in p['candidates'] if c['id']==assessment['choice'])
            if any(overlap(edit['interval'],d['interval']) for d in selected): raise ValueError('Selected treatments overlap')
            selected.append(render_insert(folder,recipe,edit,candidate,native,quality))
    with FilmCraft() as f:
        f.command('file.open',path=str(native))
        if selected:
            _,seq=native_read(native)
            f.command('sequence.addTracks',video=1,audio=0)
            track='V'+str(len(seq['video_tracks'])+1)
            for dep in selected:
                c=dep['candidate']
                if c['replace_generated_cards']: f.command('clip.enable',clips=[int(x) for x in c['replace_generated_cards']])
                imported=f.command('file.import',paths=[dep['path']])
                if imported.get('errors') or len(imported['items'])!=1: raise ValueError('Insert import failed')
                placed=f.command('timeline.place',item=imported['items'][0],track=track,frame=dep['interval']['start'],
                          duration=round(dep['frames']*TICKS*recipe['timebase']['den']/recipe['timebase']['num']),video=True,audio=False)
                f.command('timeline.select',clips=placed['clips'],add=False,toggle=False)
                f.command('clip.scaleToFrameSize')
        f.command('file.saveAs',path=str(target))
    # No existing audio or caption is replaced or added by insert application.
    _,before=native_read(native);_,after=native_read(target)
    for key in ['audio_tracks','caption_tracks','settings']:
        if before[key]!=after[key]: raise ValueError('Native audio, captions or canvas changed')
    return selected


def finalize(recipe_path):
    require_deployment()
    with exclusive(recipe_path.resolve().parent):
        return _finalize(recipe_path)


def _finalize(recipe_path):
    """Explicit CLI operation: approval required, never calls an editorial model."""
    from types import SimpleNamespace
    from stage6_finalize import Finalize, alignment, cut_master, media_info, scaled_sequence
    from stage3_sources import pool
    recipe_path=recipe_path.resolve();folder=recipe_path.parent;recipe=read(recipe_path);validate_inputs(recipe,folder)
    approval=read(folder/'approval.json')
    report=read(folder/'preview-report.json')
    if approval.get('recipe_sha256')!=file_hash(recipe_path) or approval.get('preview_sha256')!=file_hash(folder/'star4-preview-540p.mp4') or approval.get('picture_and_sound_reviewed') is not True:
        raise ValueError('Picture and sound approval does not match this recipe and preview')
    if not report['gate']['passed'] and report['applied']:
        raise ValueError('Automatic edits have no calibrated approval')
    project=Path(recipe['project']);work=folder/'final';work.mkdir(exist_ok=True)
    videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
    existing={}
    for path in (project/'media/jev/script-first/stage6').glob('*/masters.json'):
        for key,value in read(path).items():
            if value.get('status')=='upgraded': existing[key]=value
    results={};upgraded={}
    cache=pool.cache_dir(project)/'jev-stage6';context=SimpleNamespace(cache=cache,status=lambda message:print(message,flush=True))
    groups={}
    for source in recipe['sources']:
        if source['flags'] or not source['master']: raise ValueError('Unresolved source mapping prevents finalization')
        groups.setdefault(source['master']['video_id'],{})[source['master']['file']]=source
    for vid,group in groups.items():
        missing=[dict(master=s['master']) for key,s in group.items() if key not in existing]
        parts=Finalize.download(context,videos[vid],missing) if missing else []
        for key,s in group.items():
            result=existing.get(key)
            if result is None:
                m=s['master'];part=next(p for p in parts if p['start']<=m['start']+1e-6 and p['end']>=m['end']-1e-6)
                result=cut_master(project,dict(master=m),Path(part['path']),part['offset'],media_info(part['path']),cache,fragment=part['kind']=='hls')
            info=media_info(project/result['file'])
            if not result.get('source_1080p') or not result.get('alignment') or not (info['height']>=1080 or info['width']>=1920):
                raise ValueError('Dependency is unverified or below HQ resolution')
            alignment(project/key,project/result['file'],media_info(project/key),info)
            result=dict(result,info=info)
            upgraded[s['native_item']]=dict(result,info=info);results[key]=result
    data,seq=native_read(folder/'input.fcproj');expected,anchors=scaled_sequence(seq,data['project']['items'],upgraded)
    native=work/'hq-native.fcproj'
    with FilmCraft() as f:
        f.command('file.open',path=str(folder/'input.fcproj'))
        for item,r in upgraded.items(): f.command('media.relink',item=item,path=str(project/r['file']),force=True,relinkOthers=False,alignTimecode=False)
        for clip,anchor in anchors.items(): f.command('effects.setParam',clip=clip,effect='motion',param='anchor',value=anchor)
        f.command('file.saveAs',path=str(native))
    _,actual=native_read(native)
    if not native_matches(expected,actual,anchors): raise ValueError('HQ replacement changed edit geometry')
    final_recipe=copy.deepcopy(recipe)
    for binding in final_recipe['media_bindings']:
        s=next(s for s in recipe['sources'] if s['id']==binding['source_id']);r=results[s['master']['file']];path=project/r['file']
        binding.update(quality='hq',path=str(path),sha256=file_hash(path),width=r['info']['width'],height=r['info']['height'])
    target=work/'final-review.fcproj'
    deps=apply_decisions(work,final_recipe,report['decisions'],target,'hq',native) if report['gate']['passed'] else []
    if not deps: shutil.copy2(native,target)
    if any(b['quality']!='hq' for dep in deps for b in dep['bindings']): raise ValueError('Proxy baked into HQ insert')
    save_json(work/'editing-recipe.json',dict(final_recipe,dependencies=deps))
    fps=recipe['timebase']['num']/recipe['timebase']['den']
    subprocess.run([CLI,'--compact','--project',str(target),'export',str(work/'final-1080p.mp4'),'--format','h264',
        '--start',str(recipe['section']['start']/fps),'--end',str(recipe['section']['end']/fps),'--scale',str(1080/recipe['canvas']['height'])],
        check=True,capture_output=True,timeout=7200)
    video=next(s for s in inspect_media(work/'final-1080p.mp4')['streams'] if s['codec_type']=='video')
    if video['height']!=1080 or int(video['nb_frames'])!=recipe['section']['end']-recipe['section']['start']:
        raise ValueError('HQ output does not preserve exact section timing')
    save_json(work/'verification.json',dict(native_geometry_matches=True,model_calls=0,dependencies=deps,masters=results,final_review=str(target),
        status='awaiting_final_picture_and_sound_review'))
    validate_inputs(recipe,folder)
    return target


def hq_samples(folder):
    """Read existing verified HQ masters for representative frames; never download."""
    from stage6_finalize import alignment,media_info,scaled_sequence
    recipe=read(folder/'editing-recipe.json');validate_inputs(recipe,folder);project=Path(recipe['project'])
    existing={}
    for p in (project/'media/jev/script-first/stage6').glob('*/masters.json'):
        existing.update({k:v for k,v in read(p).items() if v.get('status')=='upgraded' and v.get('source_1080p')})
    available=[s for s in recipe['sources'] if s['master'] and s['master']['file'] in existing and not s['flags']]
    cases=[]
    for label,predicate in [('normal',lambda c:c['speed']==1),('retimed',lambda c:c['speed']!=1),
        ('animated',lambda c:any(p.get('keyframes') for e in c['effects'] for p in e.get('params',{}).values()))]:
        source=next((s for s in available if predicate(s['native_clip'])),None)
        if source: cases.append((label,source))
    work=folder/'hq-samples';work.mkdir(exist_ok=True);results=[]
    data,seq=native_read(folder/'input.fcproj');fps=recipe['timebase']['num']/recipe['timebase']['den']
    for label,source in cases:
        result=existing[source['master']['file']];path=project/result['file'];info=media_info(path)
        if not (info['width']>=1920 or info['height']>=1080): raise ValueError('Saved HQ sample is below resolution')
        checks=alignment(project/source['master']['file'],path,media_info(project/source['master']['file']),info)
        upgraded={source['native_item']:dict(result,info=info)};expected,anchors=scaled_sequence(seq,data['project']['items'],upgraded)
        native=work/(label+'.fcproj')
        with FilmCraft() as f:
            f.command('file.open',path=str(folder/'input.fcproj'))
            f.command('media.relink',item=source['native_item'],path=str(path),force=True,relinkOthers=False,alignTimecode=False)
            for clip,anchor in anchors.items():f.command('effects.setParam',clip=clip,effect='motion',param='anchor',value=anchor)
            f.command('file.saveAs',path=str(native))
        if not native_matches(expected,native_read(native)[1],anchors): raise ValueError('HQ sample changed native geometry')
        at=(source['timeline_interval']['start']+source['timeline_interval']['end'])/2/fps
        for suffix,input_path in [('proxy',folder/'input.fcproj'),('hq',native)]:
            output=work/(label+'-'+suffix+'.png')
            if not output.exists():
                subprocess.run([CLI,'--compact','--project',str(input_path),'render','--seconds',str(at),'--out',str(output),'--scale',str(1080/recipe['canvas']['height'])],
                    check=True,capture_output=True,timeout=600)
        results.append(dict(label=label,source_id=source['id'],timeline_seconds=at,alignment=checks,hq_binding=str(path),hq_sha256=file_hash(path)))
    validate_inputs(recipe,folder);save_json(work/'verification.json',dict(cases=results,model_calls=0,new_downloads=0,finalized=False))
    (work/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>HQ sample comparisons</title><style>body{font:16px system-ui;max-width:1600px;margin:auto}img{width:49%}</style><h1>Existing proxy / verified HQ samples</h1><p>Matching native timing, effects and captions. No final upgrade or download was performed.</p>'+''.join('<h2>'+html.escape(r['label'])+'</h2><p>Proxy left; HQ right.</p><img src="'+r['label']+'-proxy.png"><img src="'+r['label']+'-hq.png">' for r in results),encoding='utf8')
    return results


def write_report(folder,recipe,result):
    from calibration_examples import catalog,preview_ui
    examples=catalog(folder)
    rows=[]
    for p,e in zip(recipe['windows'],recipe['edits']):
        r=result['decisions'][p['id']];a=r['assessment']; t=(e['interval']['start']-recipe['section']['start'])*recipe['timebase']['den']/recipe['timebase']['num']
        rows.append('<tr><td>'+html.escape(p['id'])+f'<br><a href="star4-preview-540p.mp4#t={t:.3f}">{t:.2f}s</a></td><td>'+html.escape(p['narration'])+'</td><td>'+html.escape(', '.join(p['flags']))+'</td><td>'+html.escape(a['choice'])+'</td></tr>')
    (folder/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Star 4 proxy editing review</title><style>body{font:16px system-ui;max-width:1400px;margin:30px auto;background:#171b24;color:#f4f0e8}td{padding:12px;border-bottom:1px solid #666}a{color:#e3bb78}video{width:960px;max-width:100%}</style><h1>Star 4: recommendations pending creator calibration</h1><p>The saved edit is preserved. No model-selected edits were applied. Existing cards, effects, captions and sound remain native.</p><video controls src="star4-preview-540p.mp4"></video><p>Label distinct calibration and held-out examples in calibration-labels.template.json, then save as calibration-labels.json. Leave unsupported or uncertain choices explicit.</p><table><tr><th>Beat</th><th>Approved narration</th><th>Review flags</th><th>Recommendation</th></tr>'+''.join(rows)+'</table>',encoding='utf8')
    label_rows=[]
    for i,p in enumerate(recipe['windows']):
        options='<option value="">Choose…</option>'+''.join('<option value="'+html.escape(o,quote=True)+'">'+html.escape(examples.get(o,{}).get('name',o))+'</option>' for o in p['options'])
        details='<details><summary>Supplied treatments and evidence</summary><pre>'+html.escape(json.dumps(dict(candidates=p['candidates'],intent=p['intent'],evidence=p['evidence']),indent=2))+'</pre></details>'
        label_rows.append('<tr><td>'+html.escape(p['id'])+'<br>'+('calibration' if i<10 else 'held-out')+'</td><td>'+html.escape(p['narration'])+'<br>'+html.escape(', '.join(p['flags']))+details+'</td><td><select aria-label="Treatment for '+html.escape(p['id'],quote=True)+'" id="choice-'+str(i)+'" onchange="document.getElementById(\'example-'+str(i)+'\').disabled=!this.value">'+options+'</select><p><button type="button" id="example-'+str(i)+'" disabled onclick="showStyle(document.getElementById(\'choice-'+str(i)+'\').value)">Watch 5-second example</button></p><label><input type="checkbox" id="supported-'+str(i)+'">Evidence supports this choice</label></td></tr>')
    payload=json.dumps(dict(criteria_sha256=recipe['criteria_sha256'],labels=[dict(id=p['id'],context_sha256=result['decisions'][p['id']]['context_sha256'],split='calibration' if i<10 else 'held-out') for i,p in enumerate(recipe['windows'])])).replace('<','\\u003c')
    script="""<script>function download(){const data=JSON.parse(document.getElementById('data').textContent);for(let i=0;i<data.labels.length;i++){data.labels[i].choice=document.getElementById('choice-'+i).value;data.labels[i].supported=document.getElementById('supported-'+i).checked;}data.labels=data.labels.filter(r=>r.choice);const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='calibration-labels.json';a.click();URL.revokeObjectURL(a.href);}</script>"""
    (folder/'calibration.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Creator calibration</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:0 16px}td{padding:12px;border-bottom:1px solid #aaa}label{display:block}select{padding:8px}pre{max-width:650px;overflow:auto}</style><h1>Creator choices</h1><p><a href="style-examples/index.html" target="_blank" rel="noopener">Learn the choices: five-second visual examples</a></p><p>Choose an option, then use its Watch 5-second example button to see the style. Compare the actual beat in the full preview before labeling.</p><p>These labels require your judgment. Model recommendations are hidden on this form. Missing intent and unsupported evidence remain ineligible even after labeling. At least 20 eligible held-out decisions must agree at 95% with zero unsupported-evidence errors.</p><p><a href="star4-preview-540p.mp4">Open full preview</a></p><button onclick="download()">Download labels</button><table>'+''.join(label_rows)+'</table><script type="application/json" id="data">'+payload+'</script>'+script+preview_ui(folder),encoding='utf8')
