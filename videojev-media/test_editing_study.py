# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import MagicMock,patch

from editing_feedback import analyze,family,import_feedback
from editing_policy import require_deployment,require_short_native,require_short_study
from editing_recipe import MODEL,TICKS,apply_decisions,file_hash,finalize,prepare,preview,read,save_json
from editing_study import SCHEMA_REPO,evaluate,packets,run_study,validate_document,validate_study
from calibration_examples import catalog


class EditingStudyTests(unittest.TestCase):
    def fixture(self,root):
        study=read(SCHEMA_REPO/'examples/editing-study/short-study.json')
        media=root/'short.mp4';media.write_bytes(b'fixture; ffprobe is mocked')
        study['media']=dict(path=str(media),sha256=file_hash(media))
        path=root/'input.json';save_json(path,study)
        return study,path

    def probe(self,duration=30):
        return dict(streams=[dict(codec_type='video')],format=dict(duration=str(duration)))

    def response(self,request,**kwargs):
        data=json.loads(request.data);stage,question=next(iter(data['questions'].items()))
        ids=list(question['criteria']);choice=ids[0];others=len(ids)-1
        response=dict(model=MODEL,answers={stage:dict(type='choice',choice=choice,probabilities={k:.98 if k==choice else .02/others for k in ids})})
        handle=MagicMock();handle.__enter__.return_value.read.return_value=json.dumps(response).encode()
        return handle

    def test_scope_blocks_full_long_video_protected_projects_and_deployment(self):
        require_short_study(120,'D:/studies/short.mp4')
        for seconds in [121,0,-1,float('nan'),True]:
            with self.assertRaises(ValueError):require_short_study(seconds)
        for path in ['D:/projects/cwi-003-jev-demo/a.mp4','D:/projects/cwi-004-complete-gta-story/a.mp4','D:/GTA History/a.mp4']:
            with self.assertRaisesRegex(ValueError,'excluded'):require_short_study(5,path)
        sequence=dict(video_tracks=[dict(items=[dict(start=0,duration=600*TICKS)])],audio_tracks=[])
        with self.assertRaises(ValueError):require_short_native(sequence,Path('short-project'))
        with self.assertRaises(RuntimeError):require_deployment()
        with patch('editing_recipe.FilmCraft') as editor:
            with self.assertRaises(RuntimeError):apply_decisions(None,None,None,None)
            with self.assertRaises(RuntimeError):finalize(Path('missing-recipe.json'))
            editor.assert_not_called()

    def test_contract_rejects_non_pop_missing_provenance_and_long_video(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);study,path=self.fixture(root);validate_document(path)
            mutations=[lambda s:s.update(duration_ms=120001),lambda s:s['beats'][0]['candidates'][0].update(motion='fade'),
                lambda s:s['beats'][2]['candidates'][1].pop('source_label')]
            for change in mutations:
                bad=copy.deepcopy(study);change(bad);save_json(path,bad)
                with self.assertRaisesRegex(ValueError,'contract'):validate_document(path)

    def test_native_rejection_creates_no_approval_lock_or_worker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);project=root/'short-project';review=root/'saved.fcproj'
            long=dict(video_tracks=[dict(items=[dict(start=0,duration=600*TICKS)])],audio_tracks=[])
            short=dict(video_tracks=[dict(items=[dict(start=0,duration=30*TICKS)])],audio_tracks=[])
            with patch('editing_recipe.native_read',return_value=({},long)),patch('editing_recipe.approve') as approval:
                with self.assertRaises(ValueError):prepare(project,review,root/'out')
                approval.assert_not_called();self.assertFalse((root/'out').exists())
            with patch('editing_recipe.native_read',return_value=({},short)),patch('editing_recipe.approve') as approval:
                with self.assertRaisesRegex(ValueError,'cannot create approval'):prepare(project,review,root/'out')
                approval.assert_not_called()
            save_json(root/'editing-recipe.json',dict(project=str(project)))
            with patch('editing_recipe.native_read',return_value=({},long)):
                with self.assertRaises(ValueError):preview(root,render=False)
                self.assertFalse((root/'editing.lock').exists())

    def test_media_and_semantic_checks_happen_before_workers_or_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);study,path=self.fixture(root);out=root/'out'
            with patch('editing_study.ClefSession') as worker,patch('editing_study.inspect_media',return_value=self.probe(180)):
                with self.assertRaisesRegex(ValueError,'two minutes'):run_study(path,out)
                worker.assert_not_called();self.assertFalse(out.exists())
            with patch('editing_study.inspect_media',return_value=self.probe()):
                mutations=[lambda s:s['media'].update(sha256='b'*64),lambda s:s.update(duration_ms=29000),
                    lambda s:s['beats'][1].update(start_ms=9999),lambda s:s['beats'][1].update(id='contrast'),
                    lambda s:s['beats'][0]['candidates'][0].update(reveal_ms=[9999,10000]),
                    lambda s:s['beats'][0]['candidates'][0].update(id='keep')]
                for change in mutations:
                    bad=copy.deepcopy(study);change(bad)
                    with self.assertRaises(ValueError):validate_study(bad,path)
                study['source_project']=str(root/'project');save_json(path,study)
                with self.assertRaisesRegex(ValueError,'separate'):run_study(path,root/'project'/'out')
                out.mkdir();prior=out/'review.html';prior.write_text('earlier review')
                with self.assertRaisesRegex(ValueError,'existing reviews'):run_study(path,out)
                self.assertEqual(prior.read_text(),'earlier review')

    def test_opportunity_is_independent_of_candidates_and_judged_without_any(self):
        with tempfile.TemporaryDirectory() as d:
            study,_=self.fixture(Path(d));work=packets(study)
            self.assertEqual([p['stage'] for p in work].count('opportunity'),3)
            self.assertEqual([p['stage'] for p in work].count('treatment'),2)
            for p in work:
                if p['stage']=='opportunity':
                    self.assertNotIn('candidates',p['state']);self.assertNotIn('motion',p['state'])
                    self.assertEqual(set(p['options']),{'graphic-helpful','footage-sufficient','uncertain'})
            study['beats'][0]['candidates'][0]['labels'][0]='NEW SUPPLIED WORDING'
            changed=packets(study)
            self.assertEqual(work[0]['context_sha256'],changed[0]['context_sha256'])
            self.assertNotEqual(work[1]['context_sha256'],changed[1]['context_sha256'])
            study['beats'][0]['narration']='Changed narration'
            self.assertNotEqual(changed[0]['context_sha256'],packets(study)[0]['context_sha256'])

    def test_independent_calls_cache_blind_labels_and_stage_specific_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);study,path=self.fixture(root);out=root/'out';original=path.read_bytes();media=Path(study['media']['path'])
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession',return_value=nullcontext()) as worker,patch('editing_study.urllib.request.urlopen',side_effect=self.response) as request:
                report=run_study(path,out)
                self.assertEqual(report['model_requests'],dict(opportunity=3,treatment=2));self.assertEqual(request.call_count,5)
                self.assertEqual(report['decisions']['road']['treatment']['status'],'not-asked')
                for row in report['decisions'].values():
                    self.assertFalse(row['opportunity']['assessment']['eligible'])
                self.assertFalse(report['deployment_enabled'])
                labels=read(out/'creator-labels.template.json')
                for row in labels['labels']:
                    row['opportunity']='graphic-helpful';row['treatment']='keep'
                labels_path=root/'labels.json';save_json(labels_path,labels)
                worker.reset_mock();request.reset_mock()
                second=run_study(path,out,labels_path)
                self.assertEqual(second['model_requests'],dict(opportunity=0,treatment=0))
                worker.assert_not_called();request.assert_not_called()
                self.assertEqual(second['evaluation']['stages'],dict(opportunity=dict(count=3,matches=3,agreement=1),treatment=dict(count=2,matches=2,agreement=1)))
                stale=copy.deepcopy(labels);stale['labels'][0]['opportunity_context_sha256']='stale'
                with self.assertRaisesRegex(ValueError,'Stale'):evaluate(study,report,stale)
                page=(out/'calibration.html').read_text(encoding='utf8')
                payload=json.loads(re.search(r'<script id="labels" type="application/json">(.*?)</script>',page,re.S)[1])
                self.assertNotIn('assessment',json.dumps(payload));self.assertNotIn('opportunity',payload['labels'][0])
                self.assertIn('Watch 5-second',page);self.assertEqual(len(catalog(out)),5)
                self.assertEqual(path.read_bytes(),original);self.assertEqual(media.read_bytes(),b'fixture; ffprobe is mocked')

    def test_worker_and_malformed_response_failures_are_not_keep_predictions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,path=self.fixture(root);out=root/'out'
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession',side_effect=RuntimeError('worker failed')):
                report=run_study(path,out)
                self.assertEqual(report['model_requests'],dict(opportunity=0,treatment=0))
                self.assertEqual(report['decisions']['contrast']['opportunity']['status'],'failed')
                self.assertNotIn('assessment',report['decisions']['contrast']['opportunity'])
            bad=MagicMock();bad.__enter__.return_value.read.return_value=b'{"model":"Cloudflare/clef-flash","answers":null}'
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession',return_value=nullcontext()),patch('editing_study.urllib.request.urlopen',return_value=bad):
                report=run_study(path,out)
                self.assertEqual(report['decisions']['contrast']['treatment']['status'],'failed')
                self.assertFalse(list((out/'decisions').glob('*.json')))

    def test_partial_cache_survives_worker_start_failure_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,path=self.fixture(root);out=root/'out'
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession',return_value=nullcontext()),patch('editing_study.urllib.request.urlopen',side_effect=self.response):
                report=run_study(path,out)
            record=report['decisions']['contrast']['treatment'];saved=out/'decisions'/(record['context_sha256']+'.json');saved.unlink()
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession',side_effect=RuntimeError('worker failed')):
                report=run_study(path,out)
            self.assertEqual(report['decisions']['contrast']['opportunity']['status'],'complete')
            self.assertEqual(report['decisions']['contrast']['treatment']['status'],'failed')
            remaining=next((out/'decisions').glob('*.json'));record=read(remaining);record['context_sha256']='changed';save_json(remaining,record)
            with patch('editing_study.inspect_media',return_value=self.probe()),patch('editing_study.ClefSession') as worker:
                with self.assertRaisesRegex(ValueError,'cache'):run_study(path,out)
                worker.assert_not_called()


class CreatorFeedbackTests(unittest.TestCase):
    def fixture(self):
        windows=[dict(id=k,narration='Supplied',options=['keep','source-card-pop','none-of-these']) for k in ['train','held','planner']]
        records={k:dict(context_sha256=k,assessment=dict(choice='keep',eligible=False)) for k in ['train','held','planner']}
        for k in ['train','held']:records[k]['response']={}
        labels=dict(criteria_sha256='frozen',labels=[dict(id=k,context_sha256=k,choice='source-card-pop' if k=='held' else 'keep',supported=True,split='calibration' if k=='train' else 'held-out') for k in records])
        return dict(criteria_sha256='frozen',windows=windows),records,labels

    def test_fallbacks_are_excluded_and_family_ids_preserved(self):
        recipe,records,labels=self.fixture();result=analyze(recipe,records,labels)
        self.assertEqual(result['live_model']['count'],2);self.assertEqual(result['live_model']['exact_agreement'],.5)
        self.assertEqual(result['live_model']['model_kept_when_creator_wanted_visual'],1)
        self.assertEqual(result['planner_only']['count'],1);self.assertFalse(result['opportunity_detection']['measured'])
        self.assertFalse(result['deployment_enabled']);self.assertEqual(family('source-card'),'source-card')
        self.assertEqual(family('source-card-pop'),'source-card')

    def test_stale_duplicate_or_unknown_creator_choices_are_rejected(self):
        recipe,records,labels=self.fixture()
        for change in [lambda x:x.update(criteria_sha256='changed'),lambda x:x['labels'].append(x['labels'][0]),
                       lambda x:x['labels'][0].update(context_sha256='changed'),lambda x:x['labels'][0].update(choice='invented')]:
            bad=copy.deepcopy(labels);change(bad)
            with self.assertRaises(ValueError):analyze(recipe,records,bad)

    def test_import_preserves_frozen_inputs_and_refuses_different_prior_labels(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'historical';folder.mkdir();recipe,records,labels=self.fixture()
            save_json(folder/'editing-recipe.json',recipe);save_json(folder/'preview-report.json',dict(decisions=records))
            exported=root/'export.json';save_json(exported,labels);before={p:p.read_bytes() for p in folder.iterdir()}
            import_feedback(folder,exported)
            for p,data in before.items():self.assertEqual(p.read_bytes(),data)
            self.assertEqual((folder/'calibration-labels.json').read_bytes(),exported.read_bytes())
            labels['labels'][0]['supported']=False;save_json(exported,labels)
            with self.assertRaisesRegex(ValueError,'Earlier creator labels'):import_feedback(folder,exported)


if __name__=='__main__':unittest.main()
