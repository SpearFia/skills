# SPDX-License-Identifier: MIT OR Apache-2.0
"""Creator-selected, proxy-only auditions of the frozen Star 4 v3 snapshot."""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess

from editing_recipe import CLI,RENDERER,TICKS,digest,exclusive,file_hash,inspect_media,native_matches,native_read,read,render_insert,save_json
from filmcraft_rpc import FilmCraft

RECIPE_SHA='0abe9bdbc597ad5631814e58ad2adaf222308fa8861746b0f0ac68585904c0ba'
LABELS_SHA='d6ca5318cc771d83dec5059a6b95397bd915bf6497f7ae5227686ec6e12c328c'
MOMENTS=[
    ('seven-rounds','7 ROUNDS',['b284','b285'],1430,['7 ROUNDS','CHAPTER 2: BOWERY GIFT'],[
        ('source-card-pop','Source card','source-card',['7 ROUNDS'],['Seven'],'CHAPTER 2: BOWERY GIFT',None)]),
    ('fight-wanted','FIGHT WON / STILL WANTED',['b326','b327','b328'],1432,['OUR GUESS','FIGHT WON / STILL WANTED'],[
        ('source-card-pop','Context card','source-card',['FIGHT WON / STILL WANTED'],['He wins the fight'],'OUR GUESS',None),
        ('comparison-pop','Paired comparison','comparison',['FIGHT WON','STILL WANTED'],['He wins the fight','still wanted'],None,'OUR GUESS')]),
    ('three-exits','ROAD / BUILDING / SWAMP',['b343','b344'],1435,['OUR GUESS','ROAD / BUILDING / SWAMP'],[
        ('progressive-pop','Three-item list','progressive',['ROAD','BUILDING','SWAMP'],['Open road','building','Grassrivers'],None,'OUR GUESS'),
        ('source-card-pop','Context card','source-card',['ROAD / BUILDING / SWAMP'],['Open road'],'OUR GUESS',None)]),
    ('star4-outcome','STAR 4: COSTLY SURVIVAL',['b346','b347'],1437,['STAR 4: COSTLY SURVIVAL','OUR GUESS'],[
        ('source-card-pop','Context card','source-card',['STAR 4: COSTLY SURVIVAL'],['Four stars goes down'],'OUR GUESS',None)]),
]


def fingerprint(path):
    return file_hash(path) if path.is_file() else None


def validate_source(review):
    recipe_path=review/'editing-recipe.json';labels_path=review/'calibration-labels.json'
    if file_hash(recipe_path)!=RECIPE_SHA or file_hash(labels_path)!=LABELS_SHA:
        raise ValueError('Only the frozen, creator-reviewed Star 4 v3 snapshot is authorized for this audition')
    recipe=read(recipe_path)
    if read(review/'prepared.json')['recipe_sha256']!=RECIPE_SHA:raise ValueError('Frozen preparation receipt changed')
    if recipe['section']!=dict(start=30233,end=45124) or recipe['timebase']!=dict(num=30,den=1):raise ValueError('Unexpected Star 4 timing')
    if file_hash(review/'input.fcproj')!=recipe['reviewed_input_sha256'] or file_hash(review/'review.fcproj')!=recipe['reviewed_input_sha256']:
        raise ValueError('Frozen timeline changed')
    project=Path(recipe['project']);control={str((project/'media/jev/script-first/stage6'/n).resolve()) for n in ['stop','run.json']}
    protected={};changes=[];controls={}
    for name,expected in recipe['inputs'].items():
        path=Path(name);actual=fingerprint(path)
        if str(path.resolve()) in control:
            controls[str(path)]=actual
            if actual!=expected:changes.append(dict(path=str(path),historical_sha256=expected,current_sha256=actual))
        elif actual!=expected:raise ValueError('Editorial input changed: '+str(path))
        else:protected[str(path)]=actual
    for binding in recipe['media_bindings']:
        if fingerprint(Path(binding['path']))!=binding['sha256']:raise ValueError('Frozen media dependency changed: '+binding['path'])
        protected[binding['path']]=binding['sha256']
    for name in ['editing-recipe.json','input.fcproj','review.fcproj','prepared.json','calibration-labels.json','star4-preview-540p.mp4','render.json']:
        path=review/name;protected[str(path)]=file_hash(path)
    if protected[str(review/'star4-preview-540p.mp4')]!=read(review/'render.json')['sha256']:raise ValueError('Frozen preview changed')
    for packet in recipe['windows']:
        if digest({k:v for k,v in packet.items() if k!='context_sha256'})!=packet['context_sha256']:raise ValueError('Frozen context changed')
    data,sequence=native_read(review/'input.fcproj')
    voices=[c for t in sequence['audio_tracks'] for c in t['items'] if c['start']*30==recipe['section']['start']*TICKS]
    if len(voices)!=1 or voices[0]['speed']!=1 or voices[0]['source_in']!=0:raise ValueError('Narration mapping needs review')
    voice=Path(data['project']['items'][str(voices[0]['item'])]['kind']['Media']['media']['File']['path'])
    cache_path=project/'media/vo-words.json';cache=read(cache_path)[voice.relative_to(project).as_posix()]
    if file_hash(voice)!=cache['sha256']:raise ValueError('Narration observations are stale')
    protected[str(voice)]=cache['sha256'];protected[str(cache_path)]=file_hash(cache_path)
    return recipe,cache['words'],protected,changes,controls


def anchor(words,phrase,interval,origin):
    normal=lambda value:re.sub(r'[^a-z0-9]','',value.casefold())
    wanted=normal(phrase);matches=[]
    for i,word in enumerate(words):
        frame=origin+round(word[1]*30)
        if not interval['start']<=frame<interval['end']-18:continue
        for n in range(1,len(phrase.split())+2):
            if normal(''.join(w[0] for w in words[i:i+n]))==wanted:
                matches.append(dict(quote=phrase,frame=frame,observed_words=[w[0] for w in words[i:i+n]],method='cached-word-observation'));break
    if len(matches)!=1:raise ValueError('Narration anchor is missing or ambiguous: '+phrase)
    return matches[0]


def make_plan(recipe,words,protected,labels):
    windows={p['id']:p for p in recipe['windows']};edits={e['id']:e for e in recipe['edits']}
    creator={row['id']:row for row in labels['labels']}
    origin=recipe['section']['start'];moments=[]
    code={str(p):file_hash(p) for p in [Path(__file__),Path(__file__).with_name('audition.html'),Path(__file__).with_name('editing_recipe.py'),RENDERER/'package-lock.json',*sorted((RENDERER/'src').glob('*.ts*'))]}
    for key,title,ids,card,labels,variants in MOMENTS:
        for beat in ids:
            if not any(c['labels']==labels for c in windows[beat]['candidates']):raise ValueError('Supplied wording changed: '+beat)
        interval=dict(start=edits[ids[0]]['interval']['start'],end=edits[ids[-1]]['interval']['end'])
        context=dict(start=max(origin,interval['start']-90),end=min(recipe['section']['end'],interval['end']+90))
        supplied=set(' / '.join(labels).split())
        candidates=[]
        for choice,name,kind,body,phrases,source,qualifier in variants:
            if not set(' / '.join(body+[source or '',qualifier or '']).split()).issubset(supplied):raise ValueError('Audition contains unsupplied wording')
            anchors=[anchor(words,phrase,interval,origin) for phrase in phrases]
            active=dict(start=anchors[0]['frame'],end=interval['end'])
            source_ids=[s['id'] for s in recipe['sources'] if s['timeline_interval']['start']<active['end'] and s['timeline_interval']['end']>active['start']]
            params=dict(labels=body,reveal_frames=[a['frame'] for a in anchors],motion='pop')
            if source:params['source_label']=source
            if qualifier:params['qualifier']=qualifier
            candidate=dict(id=choice,name=name+' · pop',kind=kind,**params,source_ids=source_ids,replace_generated_cards=[str(card)])
            candidates.append(dict(id=choice,name=candidate['name'],interval=active,anchors=anchors,candidate=candidate))
        flags=sorted({f for beat in ids for f in windows[beat]['flags']})
        moments.append(dict(id=key,title=title,beat_ids=ids,card_id=card,original_text='\n'.join(labels),interval=interval,context=context,flags=flags,variants=candidates,
            creator_evidence_checked=all(creator[bid]['supported'] for bid in ids)))
    plan=dict(version=1,mode='creator-audition',source_recipe_sha256=RECIPE_SHA,creator_labels_sha256=LABELS_SHA,
        source_fingerprints=protected,renderer_fingerprints=code,moments=moments,section=recipe['section'],fps=30,width=960,height=540,
        model_calls=0,video_queries=0,hq_downloads=0,deployment_enabled=False)
    plan['context_sha256']=digest(plan)
    return plan


def run_command(command,log):
    with log.open('w',encoding='utf8') as stream:
        result=subprocess.run([str(v) for v in command],stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
    if result.returncode:raise RuntimeError('Render failed; see '+str(log))


def cached_artifact(path,identity,action):
    receipt=path.with_suffix(path.suffix+'.json')
    if receipt.exists():
        saved=read(receipt)
        if saved['identity']!=identity or fingerprint(path)!=saved['sha256']:raise ValueError('Cached audition artifact changed: '+str(path))
        return path
    if path.exists():raise ValueError('Partial audition artifact retained for diagnosis: '+str(path))
    action()
    save_json(receipt,dict(identity=identity,sha256=file_hash(path)))
    return path


def verify_media(path,frames,audio):
    info=inspect_media(path);video=next(s for s in info['streams'] if s['codec_type']=='video')
    if (video['width'],video['height'],int(video['nb_frames']))!=(960,540,frames) or any(s['codec_type']=='audio' for s in info['streams'])!=audio:
        raise ValueError('Audition resolution, frame count or audio differs: '+str(path))
    if abs(float(info['format']['duration'])-frames/30)>.06:raise ValueError('Audition timing differs')


def extract_audio(source,window,origin,work):
    audio=work/'original-audio.m4a';a=window['start']-origin;b=window['end']-origin
    identity=digest(dict(source=file_hash(source),start_sample=a*1600,end_sample=b*1600))
    return cached_artifact(audio,identity,lambda:run_command(['ffmpeg','-v','error','-nostdin','-i',source,'-vn','-af',f'atrim=start_sample={a*1600}:end_sample={b*1600},asetpts=PTS-STARTPTS','-c:a','aac','-b:a','192k',audio],work/'audio.log'))


def audio_payload_sha(path):
    result=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-'],capture_output=True,text=True,check=True,timeout=60)
    return result.stdout.strip()


def mux(video,audio,output):
    identity=digest(dict(video=file_hash(video),audio=file_hash(audio)))
    def build():
        run_command(['ffmpeg','-v','error','-nostdin','-i',video,'-i',audio,'-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart',output],output.with_suffix('.mux.log'))
        if audio_payload_sha(output)!=audio_payload_sha(audio):raise ValueError('Audition audio stream differs from the original mix segment')
    return cached_artifact(output,identity,build)


def export_video(native,window,path):
    identity=digest(dict(native=file_hash(native),window=window,cli=file_hash(Path(CLI))))
    frames=window['end']-window['start']
    def render():
        run_command([CLI,'--compact','--project',native,'export',path,'--format','h264','--start',window['start']/30,'--end',window['end']/30,'--scale',.25,'--settings',json.dumps(dict(burnCaptions=True)),'--no-audio'],path.with_suffix('.export.log'))
        verify_media(path,frames,False)
    return cached_artifact(path,identity,render)


def assemble_native(source,target,deps,card_ids):
    identity=digest(dict(source=file_hash(source),dependencies=deps,cards=card_ids))
    def build():
        _,before=native_read(source);expected=copy.deepcopy(before)
        clips={c['id']:c for t in before['video_tracks'] for c in t['items']}
        if not set(card_ids).issubset(clips):raise ValueError('Mapped original graphic is missing')
        for t in expected['video_tracks']:
            for c in t['items']:
                if c['id'] in card_ids:c['enabled']=False
        with FilmCraft() as f:
            f.command('file.open',path=str(source))
            enabled=[cid for cid in card_ids if clips[cid]['enabled']]
            if enabled:f.command('clip.enable',clips=enabled)
            if deps:
                f.command('sequence.addTracks',video=1,audio=0)
                track='V'+str(len(before['video_tracks'])+1)
                for dep in deps:
                    imported=f.command('file.import',paths=[dep['path']])
                    if imported.get('errors') or len(imported['items'])!=1:raise RuntimeError('Audition insert import failed')
                    placed=f.command('timeline.place',item=imported['items'][0],track=track,frame=dep['interval']['start'],duration=dep['frames']*TICKS//30,video=True,audio=False)
                    f.command('timeline.select',clips=placed['clips'],add=False,toggle=False);f.command('clip.scaleToFrameSize')
            f.command('file.saveAs',path=str(target))
        _,after=native_read(target)
        observed=copy.deepcopy(after)
        if deps:
            if len(after['video_tracks'])!=len(before['video_tracks'])+1:raise ValueError('Unexpected audition track changes')
            added=observed['video_tracks'].pop()
            if len(added['items'])!=len(deps):raise ValueError('Audition placements differ')
            for c,dep in zip(added['items'],deps):
                if (c['start'],c['duration'],c['source_in'],c['speed'],c['reverse'])!=(dep['interval']['start']*TICKS//30,dep['frames']*TICKS//30,0,1,False):raise ValueError('Audition insert timing differs')
        if not native_matches(expected,observed,{}):raise ValueError('Existing timeline, audio, captions or effects changed')
    return cached_artifact(target,identity,build)


def insert(out,recipe,source,moment,variant):
    candidate=variant['candidate'];params={k:candidate[k] for k in ['labels','motion','reveal_frames','source_label','qualifier'] if k in candidate}
    edit=dict(id=moment['id'],interval=variant['interval'],source_ids=candidate['source_ids'],narration_anchors=[dict(word_id=a['quote'],frame=a['frame']) for a in variant['anchors']],
        treatment=dict(kind=candidate['kind'],parameters=params),captions=[],sounds=[],decision=dict(context_sha256=digest(variant),status='recommendation'))
    derived=dict(recipe,edits=[edit],windows=[dict(id=moment['id'],context_sha256=digest(variant),candidates=[candidate],options=['keep',candidate['id'],'none-of-these'],flags=moment['flags'],evidence_adequate=False)])
    dep=render_insert(out,derived,edit,candidate,source,'proxy')
    save_json(Path(dep['path']).parent/'audition-recipe.json',derived)
    return dep


def validate_selections(plan,selected):
    if selected.get('context_sha256')!=plan['context_sha256']:raise ValueError('Selections refer to a stale audition')
    rows=selected.get('selections',[])
    if len(rows)!=len(plan['moments']) or len({r['id'] for r in rows})!=len(rows):raise ValueError('Choose every moment exactly once')
    lookup={m['id']:m for m in plan['moments']}
    for row in rows:
        if row['id'] not in lookup or row['choice'] not in {'keep','flag',*[v['id'] for v in lookup[row['id']]['variants']]}:raise ValueError('Unknown audition choice')
    return {r['id']:r['choice'] for r in rows}


def write_gallery(out,plan,clips,changes):
    data=dict(context_sha256=plan['context_sha256'],moments=[dict(m,clips=clips[m['id']]) for m in plan['moments']],control_changes=changes)
    payload=json.dumps(data,ensure_ascii=True).replace('<',chr(92)+'u003c')
    template=Path(__file__).with_name('audition.html').read_text(encoding='utf8')
    (out/'index.html').write_text(template.replace('AUDITION_DATA',payload),encoding='utf8')


def run(review,out,selections=None):
    review=review.resolve();out=out.resolve()
    recipe,words,protected,changes,controls=validate_source(review);plan=make_plan(recipe,words,protected,read(review/'calibration-labels.json'))
    if out.is_relative_to(review) or any((p/'.git').exists() or (p/'project.json').exists() for p in [out,*out.parents]):raise ValueError('Use a separate audition folder outside projects and Git')
    if out.exists() and not (out/'audition-plan.json').exists() and any(out.iterdir()):raise ValueError('Existing review must be preserved; use a fresh audition folder')
    choices=validate_selections(plan,read(selections)) if selections else None
    out.mkdir(parents=True,exist_ok=True)
    with exclusive(out):
        frozen=out/'audition-plan.json'
        if frozen.exists() and read(frozen)!=plan:raise ValueError('Audition inputs or renderer changed; preserve this review and use a fresh folder')
        if not frozen.exists():save_json(frozen,plan)
        source=out/'input.fcproj'
        if source.exists() and file_hash(source)!=recipe['reviewed_input_sha256']:raise ValueError('Audition input changed')
        if not source.exists():shutil.copy2(review/'input.fcproj',source)
        _,seq=native_read(source);native_clips={c['id']:c for t in seq['video_tracks'] for c in t['items']}
        clips={};dependencies={}
        for moment in plan['moments']:
            card=native_clips[moment['card_id']]
            text=next(e['params']['text']['value']['Text'] for e in card['effects'] if e['effect']=='graphic_text')
            if text!=moment['original_text']:raise ValueError('Mapped native card wording differs')
            work=out/moment['id'];work.mkdir(exist_ok=True);window=moment['context'];frames=window['end']-window['start']
            audio=extract_audio(review/'star4-preview-540p.mp4',window,recipe['section']['start'],work)
            baseline=export_video(source,window,work/'keep-picture.mp4')
            base=mux(baseline,audio,work/'keep.mp4');verify_media(base,frames,True)
            clips[moment['id']]={'keep':str(base.relative_to(out)).replace('\\','/')}
            for variant in moment['variants']:
                print('Audition: '+moment['title']+' / '+variant['name'],flush=True)
                dep=insert(out,recipe,source,moment,variant);dependencies[moment['id']+'|'+variant['id']]=dep
                project=assemble_native(source,work/(variant['id']+'.fcproj'),[dep],[moment['card_id']])
                picture=export_video(project,window,work/(variant['id']+'-picture.mp4'))
                video=mux(picture,audio,work/(variant['id']+'.mp4'));verify_media(video,frames,True)
                clips[moment['id']][variant['id']]=str(video.relative_to(out)).replace('\\','/')
        result=dict(context_sha256=plan['context_sha256'],model_calls=0,video_queries=0,hq_downloads=0,deployment_enabled=False,control_changes=changes,clips=clips)
        if choices is not None:
            key=digest(choices);full=out/'selections'/key;full.mkdir(parents=True,exist_ok=True);save_json(full/'creator-selections.json',read(selections))
            deps=[dependencies[m['id']+'|'+choices[m['id']]] for m in plan['moments'] if choices[m['id']] not in {'keep','flag'}]
            cards=[m['card_id'] for m in plan['moments'] if choices[m['id']] not in {'keep','flag'}]
            project=assemble_native(source,full/'review.fcproj',deps,cards)
            picture=export_video(project,recipe['section'],full/'section-picture.mp4')
            preview=mux(picture,review/'star4-preview-540p.mp4',full/'star4-preview-540p.mp4')
            verify_media(preview,14891,True)
            result['full_section']=dict(project=str(project),preview=str(preview),unresolved=[k for k,v in choices.items() if v=='flag'],approval='pending picture and sound review')
        for name,expected in protected.items():
            if fingerprint(Path(name))!=expected:raise ValueError('Protected render input changed during audition: '+name)
        for name,expected in plan['renderer_fingerprints'].items():
            if fingerprint(Path(name))!=expected:raise ValueError('Renderer changed during audition: '+name)
        result['protected_inputs_unchanged']=True
        result['control_state_before']=controls;result['control_state_after']={name:fingerprint(Path(name)) for name in controls}
        save_json(out/'completion-checks.json',result)
        write_gallery(out,plan,clips,changes)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--review',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--selections',type=Path)
    args=parser.parse_args();result=run(args.review,args.out,args.selections);print(json.dumps(dict(gallery=str(args.out/'index.html'),model_calls=result['model_calls'],protected_inputs_unchanged=result['protected_inputs_unchanged'])))
