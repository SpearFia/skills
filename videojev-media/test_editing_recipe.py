# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editing_recipe import MODEL,REVISION,assess,attach_evidence,calibration_gate,decisions,digest,exclusive,file_hash,native_matches,reveal_anchors,render_insert,supported,validate_inputs


class RecipeTests(unittest.TestCase):
    def test_two_operations_cannot_own_one_review(self):
        with tempfile.TemporaryDirectory() as d:
            with exclusive(Path(d)):
                with self.assertRaisesRegex(RuntimeError,'Another editing operation'):
                    with exclusive(Path(d)):pass

    def packet(self):
        p=dict(id='a',options=['keep','progressive','none-of-these'],candidates=[dict(id='progressive')],flags=[],evidence_adequate=True)
        p['context_sha256']=digest(p)
        return p

    def response(self):
        return dict(model=MODEL,answers=dict(treatment=dict(type='choice',choice='progressive',probabilities=dict(keep=.02,progressive=.97,**{'none-of-these':.01}))))

    def test_probabilities_abstention_and_evidence(self):
        p=self.packet();r=self.response();self.assertTrue(assess(p,r)['eligible'])
        p['evidence_adequate']=False;self.assertFalse(assess(p,r)['eligible'])
        p['evidence_adequate']=True;p['flags']=['missing intent'];self.assertFalse(assess(p,r)['eligible'])
        for value in [float('nan'),float('inf'),-1,True,.1]:
            bad=copy.deepcopy(r);bad['answers']['treatment']['probabilities']['progressive']=value
            with self.assertRaises(ValueError):assess(p,bad)
        r['answers']['treatment'].update(choice='none-of-these',probabilities={'keep':.01,'progressive':.01,'none-of-these':.98})
        self.assertFalse(assess(p,r)['eligible'])

    def test_distinct_held_out_creator_labels_gate_application(self):
        labels=dict(criteria_sha256='frozen',labels=[dict(id='train',split='calibration',context_sha256='train',choice='keep',supported=True)])
        records={'train':dict(context_sha256='train',assessment=dict(eligible=True,choice='keep'))}
        for i in range(20):
            key=str(i);records[key]=dict(context_sha256=key,assessment=dict(eligible=True,choice='keep'))
            labels['labels'].append(dict(id=key,split='held-out',context_sha256=key,choice='keep',supported=True))
        self.assertTrue(calibration_gate(records,labels,'frozen')['passed'])
        labels['labels'][-1]['supported']=False;self.assertFalse(calibration_gate(records,labels,'frozen')['passed'])
        labels['labels'][-1]['context_sha256']='stale'
        with self.assertRaises(ValueError):calibration_gate(records,labels,'frozen')

    def test_source_bounds_question_identity_and_unsupported_time_mapping(self):
        source=dict(flags=[],lineage=dict(source_id='film'),source_interval=dict(start=10*254016000000,end=12*254016000000))
        observation=dict(video_id='film',question_id='q',start=9,end=13)
        self.assertEqual(attach_evidence(source,{'q'},[observation]),[observation])
        self.assertFalse(attach_evidence(source,{'other'},[observation]))
        self.assertFalse(attach_evidence(source,{'q'},[dict(observation,end=11)]))
        for c in [dict(speed=-1),dict(speed=1,reverse=True),dict(speed=1,frame_hold={}),dict(speed=1,effects=[dict(effect='time_remap',params=dict(speed=dict(keyframes=[1])))])]:
            self.assertFalse(supported(c))
        self.assertTrue(supported(dict(speed=.5)))

    def test_cache_is_semantic_and_worker_failure_keeps_current(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.packet()
            response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=json.dumps(self.response()).encode()
            with patch('editing_recipe.urllib.request.urlopen',return_value=response) as request:
                first,calls=decisions(root,[p]);self.assertEqual(calls,1)
                _,calls=decisions(root,[p]);self.assertEqual(calls,0);self.assertEqual(request.call_count,1)
            p['context_sha256']='changed'
            with patch('editing_recipe.urllib.request.urlopen',side_effect=OSError('worker failed')):
                records,_=decisions(root,[p]);self.assertEqual(records['a']['assessment']['choice'],'keep')
                self.assertFalse(records['a']['assessment']['eligible'])

    def test_changed_inputs_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'input.fcproj').write_text('native')
            recipe=dict(reviewed_input_sha256=file_hash(root/'input.fcproj'),inputs={},media_bindings=[],windows=[])
            validate_inputs(recipe,root)
            (root/'input.fcproj').write_text('changed')
            with self.assertRaises(ValueError):validate_inputs(recipe,root)

    def test_anchor_rounding_never_relaxes_edit_timing(self):
        clip={'id':1,'duration':300,'effects':[{'effect':'motion','params':{'anchor':{'value':{'Vec2':{'x':959.9999999999999,'y':540}}}}}]}
        expected=dict(video_tracks=[dict(items=[clip])]);actual=copy.deepcopy(expected)
        actual['video_tracks'][0]['items'][0]['effects'][0]['params']['anchor']['value']['Vec2']['x']=960
        self.assertTrue(native_matches(expected,actual,{1:[960,540]}))
        actual['video_tracks'][0]['items'][0]['duration']=301
        self.assertFalse(native_matches(expected,actual,{1:[960,540]}))

    def test_reveals_require_unique_supplied_anchors_and_measured_words(self):
        text='ACTION: Reveal "A" at "hello"; Reveal "B" at "world"'
        words=[dict(text='hello',startFrame=0),dict(text='world',startFrame=30)]
        args=(text,['A','B'],words,[['hello',0,.2],['world',1,1.2]],100,30,30,dict(start=100,end=200))
        self.assertEqual(reveal_anchors(*args),[100,130])
        self.assertIsNone(reveal_anchors(text,['unknown'],*args[2:]))

    def test_hq_insert_refuses_proxy_dependency_before_rendering(self):
        with tempfile.TemporaryDirectory() as d:
            recipe=dict(sources=[dict(id='a')],media_bindings=[dict(source_id='a',quality='proxy')])
            with self.assertRaisesRegex(ValueError,'verified resolution'):
                render_insert(Path(d),recipe,{},dict(source_ids=['a']),Path(d)/'native.fcproj','hq')


if __name__=='__main__':unittest.main()
