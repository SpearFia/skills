# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import editing_audition as a
from editing_recipe import TICKS,digest,file_hash,native_read,read,save_json


class FakeFilmCraft:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def command(self,command,**p):
        if command=='file.open':self.data,self.seq=native_read(Path(p['path']))
        elif command=='clip.enable':
            for t in self.seq['video_tracks']:
                for c in t['items']:
                    if c['id'] in p['clips']:c['enabled']=not c['enabled']
        elif command=='captions.setTrack':self.seq['caption_tracks'][int(p['track'][1:])-1]['enabled']=p['enabled']
        elif command=='sequence.addTracks':self.seq['video_tracks'].append(dict(id=999,name='Audition',items=[]))
        elif command=='file.import':return dict(items=[888],errors=[])
        elif command=='timeline.place':
            c=dict(id=1000+len(self.seq['video_tracks'][-1]['items']),start=p['frame']*TICKS//30,duration=p['duration'],source_in=0,speed=1,reverse=False,enabled=True,effects=[])
            self.seq['video_tracks'][-1]['items'].append(c);return dict(clips=[c['id']])
        elif command in ['timeline.select','clip.scaleToFrameSize']:pass
        elif command=='file.saveAs':save_json(Path(p['path']),self.data)
        else:raise AssertionError(command)


class AuditionTests(unittest.TestCase):
    def fixture(self,root):
        review=root/'historical';review.mkdir();project=root/'project';project.mkdir()
        editorial=project/'script.md';editorial.write_text('approved script')
        controls=project/'media/jev/script-first/stage6';controls.mkdir(parents=True)
        (controls/'stop').write_text('stop');(controls/'run.json').write_text('{}')
        voice=project/'A-roll/voiceover/06_star-4.mp3';voice.parent.mkdir(parents=True);voice.write_bytes(b'voice')
        observations=[['Seven',201.1,201.62],['He',401.46,401.62],['wins',401.62,401.82],['the',401.82,402],['fight',402,402.28],['still',403.26,403.54],['wanted.',403.54,403.94],
            ['Open',477.36,477.64],['road,',477.64,477.96],['building',478.54,478.76],['grass',480.22,480.6],['rivers',480.6,480.84],['Four',487.6,487.9],['stars',487.9,488.14],['goes',488.14,488.48],['down',488.48,488.78]]
        save_json(project/'media/vo-words.json',{'A-roll/voiceover/06_star-4.mp3':dict(sha256=file_hash(voice),words=observations)})
        clips=[dict(id=m[3],name=m[1],start=0,duration=TICKS*3,enabled=True,effects=[dict(effect='graphic_text',params=dict(text=dict(value=dict(Text='\n'.join(m[4]))),position=dict(value=dict(Vec2=dict(x=1920.,y=1994.4)))))]) for m in a.MOMENTS]
        clips.append(dict(id=1505,name='Adjustment Layer',enabled=True,effects=[]))
        seq=dict(settings=dict(width=3840,height=2160),video_tracks=[dict(id=1,name='Picture',items=clips)],audio_tracks=[dict(items=[dict(id=6,item=6,start=30233*TICKS//30,duration=14891*TICKS//30,source_in=0,speed=1)])],caption_tracks=[dict(id=7,enabled=True,captions=[dict(text='native caption',start=3,duration=5)])])
        data=dict(format='filmcraft.project',project=dict(items={'1':dict(kind=dict(Sequence=seq)),'6':dict(kind=dict(Media=dict(media=dict(File=dict(path=str(voice))))))}))
        save_json(review/'input.fcproj',data);shutil.copy2(review/'input.fcproj',review/'review.fcproj')
        (review/'star4-preview-540p.mp4').write_bytes(b'baseline');save_json(review/'render.json',dict(sha256=file_hash(review/'star4-preview-540p.mp4')))
        times=[(36266,36365),(36365,36568),(41991,42088),(42088,42277),(42277,42370),(44424,44554),(44554,44705),(44861,44968),(44968,45124)]
        windows=[];edits=[];i=0
        for m in a.MOMENTS:
            for bid in m[2]:
                w=dict(id=bid,candidates=[dict(labels=m[4])],flags=['manual-effect-or-overlay-conflict'],evidence_adequate=False)
                w['context_sha256']=digest(w);windows.append(w);edits.append(dict(id=bid,interval=dict(start=times[i][0],end=times[i][1])));i+=1
        media=root/'proxy.mp4';media.write_bytes(b'proxy')
        recipe=dict(section=dict(start=30233,end=45124),timebase=dict(num=30,den=1),canvas=dict(width=3840,height=2160),project=str(project),reviewed_input_sha256=file_hash(review/'input.fcproj'),
            inputs={str(p):file_hash(p) for p in [editorial,controls/'stop',controls/'run.json']},media_bindings=[dict(source_id='shot',path=str(media),sha256=file_hash(media),quality='proxy')],
            sources=[dict(id='shot',timeline_interval=dict(start=30233,end=45124))],windows=windows,edits=edits)
        save_json(review/'editing-recipe.json',recipe);save_json(review/'prepared.json',dict(recipe_sha256=file_hash(review/'editing-recipe.json')))
        save_json(review/'calibration-labels.json',dict(labels=[dict(id=bid,supported=bid not in ['b284','b285']) for m in a.MOMENTS for bid in m[2]]))
        renderer=root/'renderer';(renderer/'src').mkdir(parents=True);(renderer/'src/a.ts').write_text('renderer');(renderer/'package-lock.json').write_text('{}')
        cli=root/'filmcraft.exe';cli.write_bytes(b'CLI fixture')
        return review,renderer,cli

    def environment(self,review,renderer,cli):
        return patch.multiple(a,RECIPE_SHA=file_hash(review/'editing-recipe.json'),LABELS_SHA=file_hash(review/'calibration-labels.json'),RENDERER=renderer,CLI=str(cli))

    def test_frozen_scope_control_changes_and_editorial_dependency_failures(self):
        with tempfile.TemporaryDirectory() as d:
            review,renderer,cli=self.fixture(Path(d))
            with self.environment(review,renderer,cli):
                r,w,p,changes,controls=a.validate_source(review);self.assertFalse(changes)
                control=Path(r['project'])/'media/jev/script-first/stage6';(control/'stop').unlink();(control/'run.json').write_text('changed by another job')
                r,w,p,changes,controls=a.validate_source(review);self.assertEqual(len(changes),2)
                plan=a.make_plan(r,w,p,read(review/'calibration-labels.json'));self.assertEqual(len(plan['moments']),4)
                self.assertFalse(plan['moments'][0]['creator_evidence_checked'])
                self.assertEqual(sum(len(m['variants']) for m in plan['moments']),6)
                self.assertFalse(plan['deployment_enabled']);self.assertEqual(plan['model_calls'],0)
                three=plan['moments'][2]['variants'][0]
                self.assertEqual(three['candidate']['labels'],['ROAD','BUILDING','SWAMP']);self.assertEqual(three['candidate']['qualifier'],'OUR GUESS')
                self.assertEqual(three['anchors'][2]['observed_words'],['grass','rivers'])
                source=plan['moments'][0]['variants'][0]['candidate'];self.assertEqual(source['labels'],['7 ROUNDS']);self.assertEqual(source['source_label'],'CHAPTER 2: BOWERY GIFT')
                Path(r['media_bindings'][0]['path']).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'media dependency'):a.validate_source(review)
            with self.assertRaisesRegex(ValueError,'Only the frozen'):a.validate_source(review)

    def test_unique_anchors_and_complete_stale_safe_choices(self):
        with tempfile.TemporaryDirectory() as d:
            review,renderer,cli=self.fixture(Path(d))
            with self.environment(review,renderer,cli):
                r,w,p,_,_=a.validate_source(review);plan=a.make_plan(r,w,p,read(review/'calibration-labels.json'))
                selected=dict(context_sha256=plan['context_sha256'],selections=[dict(id=m['id'],choice='keep') for m in plan['moments']])
                self.assertEqual(len(a.validate_selections(plan,selected)),4)
                for change in [lambda s:s.update(context_sha256='stale'),lambda s:s['selections'].pop(),lambda s:s['selections'].append(s['selections'][0]),lambda s:s['selections'][0].update(choice='comparison-pop')]:
                    bad=copy.deepcopy(selected);change(bad)
                    with self.assertRaises(ValueError):a.validate_selections(plan,bad)
                with self.assertRaisesRegex(ValueError,'missing or ambiguous'):a.anchor([['Seven',201.1,201.6],['Seven',202.,202.3]],'Seven',dict(start=36266,end=36568),30233)
                with self.assertRaisesRegex(ValueError,'missing or ambiguous'):a.anchor(w,'unknown phrase',dict(start=36266,end=36568),30233)

    def test_full_mocked_pipeline_preserves_source_and_warm_rerun_does_no_rendering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);review,renderer,cli=self.fixture(root);out=root/'audition';frames={};audio={};calls=[]
            def process(command,**kwargs):
                calls.append(command)
                if command[0]==str(cli):
                    path=Path(command[command.index('export')+1]);n=round((float(command[command.index('--end')+1])-float(command[command.index('--start')+1]))*30);has_audio=False
                elif command[0]=='node':path=Path(command[5]);n=read(Path(command[command.index('--props')+1]))['duration'];has_audio=False
                else:
                    path=Path(command[-1]);is_mux='-map' in command;n=frames[str(command[command.index('-i')+1])] if is_mux else 0;has_audio=True
                path.write_bytes(('render:'+str(path)).encode());frames[str(path)]=n;audio[str(path)]=has_audio
                return SimpleNamespace(returncode=0)
            def probe(path):
                streams=[dict(codec_type='video',width=960,height=540,nb_frames=frames[str(path)])]
                if audio[str(path)]:streams.append(dict(codec_type='audio'))
                return dict(streams=streams,format=dict(duration=frames[str(path)]/30))
            with self.environment(review,renderer,cli),patch('editing_recipe.CLI',str(cli)),patch('editing_recipe.RENDERER',renderer),patch('editing_recipe.FilmCraft',FakeFilmCraft),patch.object(a,'FilmCraft',FakeFilmCraft),patch('subprocess.run',side_effect=process),patch.object(a,'inspect_media',side_effect=probe),patch('editing_recipe.inspect_media',side_effect=probe),patch.object(a,'audio_payload_sha',return_value='identical'),patch('urllib.request.urlopen',side_effect=AssertionError('No model or video queries are authorized')):
                before={p:p.read_bytes() for p in review.iterdir()}
                report=a.run(review,out);self.assertTrue(report['protected_inputs_unchanged']);first_calls=len(calls);self.assertGreater(first_calls,0)
                exports=[c for c in calls if c[0]==str(cli)]
                self.assertTrue(all(json.loads(c[c.index('--settings')+1])['burnCaptions'] for c in exports if '--settings' in c))
                self.assertEqual(len(report['clips']),4);self.assertNotIn('full_section',report)
                self.assertEqual(a.run(review,out),report);self.assertEqual(len(calls),first_calls)
                for p,data in before.items():self.assertEqual(p.read_bytes(),data)
                plan=read(out/'audition-plan.json');selected=dict(context_sha256=plan['context_sha256'],selections=[dict(id=m['id'],choice='flag' if m['id']=='three-exits' else m['variants'][0]['id']) for m in plan['moments']])
                choices=root/'choices.json';save_json(choices,selected)
                full=a.run(review,out,choices);self.assertEqual(full['full_section']['unresolved'],['three-exits'])
                _,native=native_read(Path(full['full_section']['project']));_,original=native_read(review/'input.fcproj')
                self.assertEqual(native['audio_tracks'],original['audio_tracks']);self.assertEqual(native['caption_tracks'],original['caption_tracks'])
                self.assertEqual(len(native['video_tracks'][-1]['items']),3)
                self.assertTrue(next(c for c in native['video_tracks'][0]['items'] if c['id']==1435)['enabled'])
                self.assertTrue(next(c for c in native['video_tracks'][0]['items'] if c['id']==1505)['enabled'])

    def test_changed_cache_is_rejected_without_rerender(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'artifact';calls=[]
            def write():calls.append(True);path.write_bytes(b'verified')
            a.cached_artifact(path,'same',write);a.cached_artifact(path,'same',write);self.assertEqual(len(calls),1)
            path.write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'changed'):a.cached_artifact(path,'same',write)
            self.assertEqual(len(calls),1)

    def test_wrong_audio_cannot_be_cached_as_a_verified_preview(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);video=root/'picture.mp4';audio=root/'audio.m4a';output=root/'preview.mp4'
            video.write_bytes(b'picture');audio.write_bytes(b'original audio')
            with patch.object(a,'run_command',side_effect=lambda *args:output.write_bytes(b'wrong mix')),patch.object(a,'audio_payload_sha',side_effect=['different','original']):
                with self.assertRaisesRegex(ValueError,'audio stream differs'):a.mux(video,audio,output)
            self.assertFalse(output.with_suffix('.mp4.json').exists())


if __name__=='__main__':unittest.main()
