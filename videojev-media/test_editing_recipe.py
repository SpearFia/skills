# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editing_recipe import MODEL,REVISION,parse_text,channel_qualifiers,text_candidates,assess,attach_evidence,calibration_gate,decisions,digest,exclusive,file_hash,native_matches,reveal_anchors,render_insert,supported,validate_inputs


class RecipeTests(unittest.TestCase):
    def test_moment_labels_match_hand_mapped_auditions(self):
        from editing_audition import MOMENTS
        qualifiers=channel_qualifiers('## Editing\nQualifiers: OUR GUESS / ESTIMATE\n## Sound\nQualifiers: NOT HERE')
        self.assertEqual(qualifiers,['OUR GUESS','ESTIMATE'])
        for key,_,_,_,lines,variants in MOMENTS:
            text='\n'.join('TEXT: '+line for line in lines)
            if key=='fight-wanted':text+='\nGRAPHIC: Paired comparison'
            parsed=parse_text(text,qualifiers)
            candidates={c['id']:c for c in text_candidates(parsed,text,None)}
            for cid,_,kind,labels,_,source,qualifier in variants:
                with self.subTest(moment=key,kind=kind):
                    c=candidates[cid]
                    self.assertEqual(c['labels'],labels)
                    self.assertEqual(c.get('source_label'),source)
                    self.assertEqual(c.get('qualifier'),qualifier)
                    self.assertNotIn('OUR GUESS',c['labels'])
                    self.assertNotIn('reveal_frames',c)
            if key=='three-exits':self.assertFalse(any(c['kind']=='comparison' for c in candidates.values()))

    def test_text_classification_is_explicit_and_channel_supplied(self):
        self.assertEqual(channel_qualifiers('## Editing\nNo list'),[])
        parsed=parse_text('TEXT: STAR 4\nTEXT: OUR GUESS')
        self.assertIn('unclassified-text-line',parsed['flags'])
        self.assertFalse(any(c['kind']=='comparison' for c in text_candidates(parsed,'',None)))
        parsed=parse_text('TEXT: STAR 4: COSTLY SURVIVAL\nTEXT: SOURCE: ledger\nTEXT: OUR GUESS',['OUR GUESS'])
        self.assertEqual(parsed['body_lines'],['STAR 4: COSTLY SURVIVAL'])
        self.assertEqual(parsed['source_label'],'SOURCE: ledger')
        c=text_candidates(parsed,'', [30])[0]
        self.assertEqual(c['source_label'],'SOURCE: ledger');self.assertEqual(c['qualifier'],'OUR GUESS')
        parsed=parse_text('TEXT: GTA 5 BASELINE / STARS 1-5')
        self.assertEqual(parsed['body_lines'],['GTA 5 BASELINE / STARS 1-5'])
        self.assertFalse(any(c['kind']=='comparison' for c in text_candidates(parsed,'', [30,60])))

    def test_handoff_lowercase_and_multiline_reveal_anchors(self):
        text='ACTION: Reveal "Fight won" at "He wins the fight"; reveal "Still wanted" at\n"he is still wanted"\nTEXT: Fight won / Still wanted\nGRAPHIC: Paired comparison'
        labels=parse_text(text)['units'];tokens='He wins the fight he is still wanted'.split()
        words=[dict(text=t,startFrame=i*10) for i,t in enumerate(tokens)]
        heard=[[t,i/3,i/3+.1] for i,t in enumerate(tokens)]
        frames=reveal_anchors(text,labels,words,heard,0,30,30,dict(start=0,end=150))
        self.assertEqual(frames,[0,40])
        parsed=parse_text(text+'\nTEXT: SOURCE: context')
        c=next(c for c in text_candidates(parsed,text,frames) if c['kind']=='source-card')
        self.assertEqual(c['reveal_frames'],[0])

    def test_grouped_probabilities_do_not_change_raw_eligibility(self):
        ps={'keep':.4,'source-card-pop':.25,'source-card-fade':.2,'comparison-pop':.1,'none-of-these':.05}
        packet=dict(options=list(ps),flags=[],evidence_adequate=True)
        response=dict(model=MODEL,answers=dict(treatment=dict(type='choice',choice='keep',probabilities=ps)))
        a=assess(packet,response)
        self.assertEqual(a['choice'],'keep');self.assertFalse(a['threshold_pass']);self.assertFalse(a['eligible'])
        self.assertAlmostEqual(a['keep_probability'],.4);self.assertAlmostEqual(a['none_probability'],.05)
        self.assertAlmostEqual(a['treatment_probability'],.55);self.assertEqual(a['grouped_choice'],'treatment')
        self.assertEqual(a['best_treatment'],'source-card-pop');self.assertEqual(a['per_kind'],{'source-card':.45,'comparison':.1})
        response['answers']['opportunity']=response['answers']['treatment']
        self.assertNotIn('grouped_choice',assess(packet,response,'opportunity'))

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
                saved=root/'decisions'/(p['context_sha256']+'.json')
                cached=json.loads(saved.read_text());cached['assessment'].pop('grouped_choice');saved.write_text(json.dumps(cached))
                second,calls=decisions(root,[p]);self.assertEqual(second['a']['assessment']['grouped_choice'],'treatment')
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

    def test_graphic_caption_roundtrip_preserves_text_timing_and_geometry(self):
        clip=dict(id=7,start=100,duration=300,source_in=20,speed=.5,effects=[dict(effect='graphic_text',params=dict(
            position=dict(value=dict(Vec2=dict(x=1920.,y=1994.4000028967857))),text=dict(value=dict(Text='Could John Wick survive a'))))])
        expected=dict(video_tracks=[dict(items=[clip])]);actual=copy.deepcopy(expected)
        graphic=actual['video_tracks'][0]['items'][0]
        graphic['effects'][0]['params']['position']['value']['Vec2']['y']=1994.4000028967855
        self.assertTrue(native_matches(expected,actual,{}))
        self.assertEqual(expected['video_tracks'][0]['items'][0]['effects'][0]['params']['position']['value']['Vec2']['y'],1994.4000028967857)
        for key,value in [('start',101),('duration',301),('source_in',21),('speed',.5000000000001)]:
            with self.subTest(key=key):
                changed=copy.deepcopy(actual);changed['video_tracks'][0]['items'][0][key]=value
                self.assertFalse(native_matches(expected,changed,{}))
        for value in [1994.4001,float('nan'),float('inf')]:
            with self.subTest(position=value):
                changed=copy.deepcopy(actual)
                changed['video_tracks'][0]['items'][0]['effects'][0]['params']['position']['value']['Vec2']['y']=value
                self.assertFalse(native_matches(expected,changed,{}))
        graphic['effects'][0]['params']['text']['value']['Text']='Changed words'
        self.assertFalse(native_matches(expected,actual,{}))

    def test_reveals_require_unique_supplied_anchors_and_measured_words(self):
        text='ACTION: Reveal "A" at "hello"; Reveal "B" at "world"'
        words=[dict(text='hello',startFrame=0),dict(text='world',startFrame=30)]
        args=(text,['A','B'],words,[['hello',0,.2],['world',1,1.2]],100,30,30,dict(start=100,end=200))
        self.assertEqual(reveal_anchors(*args),[100,130])
        self.assertIsNone(reveal_anchors(text,['unknown'],*args[2:]))

    def test_caption_graphic_roundoff_never_relaxes_text_or_timing(self):
        clip=dict(id=7,start=100,duration=300,source_in=20,speed=.5,effects=[dict(effect='graphic_text',params=dict(
            position=dict(value=dict(Vec2=dict(x=1920.,y=1994.4000028967857))),text=dict(value=dict(Text='Native caption'))))])
        expected=dict(video_tracks=[dict(items=[clip])]);actual=copy.deepcopy(expected)
        actual['video_tracks'][0]['items'][0]['effects'][0]['params']['position']['value']['Vec2']['y']=1994.4000028967855
        self.assertTrue(native_matches(expected,actual,{}))
        self.assertEqual(expected['video_tracks'][0]['items'][0]['effects'][0]['params']['position']['value']['Vec2']['y'],1994.4000028967857)
        for field,value in [('start',101),('duration',301),('source_in',21),('speed',.5000000000001)]:
            bad=copy.deepcopy(actual);bad['video_tracks'][0]['items'][0][field]=value
            self.assertFalse(native_matches(expected,bad,{}))
        bad=copy.deepcopy(actual);bad['video_tracks'][0]['items'][0]['effects'][0]['params']['text']['value']['Text']='Changed caption'
        self.assertFalse(native_matches(expected,bad,{}))

    def test_hq_insert_refuses_proxy_dependency_before_rendering(self):
        with tempfile.TemporaryDirectory() as d:
            recipe=dict(sources=[dict(id='a')],media_bindings=[dict(source_id='a',quality='proxy')])
            with self.assertRaisesRegex(ValueError,'verified resolution'):
                render_insert(Path(d),recipe,{},dict(source_ids=['a']),Path(d)/'native.fcproj','hq')


if __name__=='__main__':unittest.main()
