# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pilot
import edit_pilot


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.cue = {'id': 'c1', 'narration': 'An exit closes', 'purpose': 'Loss of exit',
                    'required': ['Exit visibly closes'], 'match': 'exact', 'start': 5., 'end': 15.,
                    'edit': {'preset': 'punch', 'start': 6., 'seconds': 1., 'text': '',
                             'reason': 'Emphasis', 'rect': [.2,.2,.3,.3]}}
        self.candidate = {'id':'a','path':'a.mp4','in':10.,'out':18.,'sha':'hash'}
        self.answer = {'in':1.,'out':5.,'fit':3,'clarity':3,'interest':2,'identity':'verified',
                       'identity_evidence':'Verified source and visible scene',
                       'checks':[{'requirement':'Exit visibly closes','verdict':'yes','at':2.,'evidence':'Door shuts'}]}

    def test_exact_uncertainty_never_becomes_accepted(self):
        self.answer['identity']='uncertain'
        self.assertEqual(pilot.verify_result(self.cue,self.candidate,self.answer)['status'],'unresolved')

    def test_required_predicate_cannot_disappear(self):
        self.answer['checks']=[]
        with self.assertRaises(ValueError):
            pilot.verify_result(self.cue,self.candidate,self.answer)

    def test_evidence_outside_final_trim_is_rejected(self):
        self.answer['in']=3.
        with self.assertRaises(ValueError):
            pilot.verify_result(self.cue,self.candidate,self.answer)

    def test_source_time_is_not_clip_time(self):
        r=pilot.verify_result(self.cue,self.candidate,self.answer)
        self.assertEqual((r['in'],r['out']),(11.,15.))

    def test_rounding_never_extends_source(self):
        self.answer['out']=8.001
        r=pilot.verify_result(self.cue,self.candidate,self.answer)
        self.assertEqual(r['out'],18.)
        self.answer['out']=8.2
        with self.assertRaises(ValueError):
            pilot.verify_result(self.cue,self.candidate,self.answer)

    def test_nonfinite_timestamps_fail(self):
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):
                pilot.num(value,0,10)

    def test_review_window_maps_to_chapter(self):
        p={'revision':0,'cues':[self.cue]}
        change={'id':'c1','observed_at':1.,'observation':'Exit visible','edit':self.cue['edit']}
        r=edit_pilot.apply_changes(p,[change],[5.,15.])
        self.assertEqual(r['cues'][0]['review']['at'],6.)
        self.assertEqual(p['revision'],0)

    def test_locked_edit_is_preserved(self):
        self.cue['locked']=True
        with self.assertRaises(ValueError):
            edit_pilot.apply_changes({'revision':0,'cues':[self.cue]},
                                    [{'id':'c1','observed_at':1.,'observation':'x','edit':self.cue['edit']}],[5.,15.])

    def test_review_cannot_escape_inspected_window(self):
        with self.assertRaises(ValueError):
            edit_pilot.apply_changes({'revision':0,'cues':[self.cue]},
                                    [{'id':'c1','observed_at':1.,'observation':'x','edit':self.cue['edit']}],[20.,30.])

    def test_plan_cannot_rewrite_narration_or_remove_qualifiers(self):
        old={'id':'c1','narration':'An exit closes','start':5.,'end':15.,'method':'Generated artwork',
             'details':{'match':'subject'},'direction':'TEXT: OUR GUESS'}
        cue={**self.cue,'method':'Generated artwork','match':'subject'}
        cue['edit']={**cue['edit'],'preset':'title','text':'OUR GUESS'}
        plan={'cues':[cue]}
        edit_pilot.validate_plan(plan,{'cues':[old]})
        cue['narration']='A new script'
        with self.assertRaises(ValueError):
            edit_pilot.validate_plan(plan,{'cues':[old]})
        cue['narration']=old['narration']
        cue['edit']['text']='CONFIRMED'
        with self.assertRaises(ValueError):
            edit_pilot.validate_plan(plan,{'cues':[old]})

    def test_changed_cue_retrieves_different_action(self):
        rows=[{'id':'a','subject':'film','analysis':{'description':'door exit closes'}},
              {'id':'b','subject':'film','analysis':{'description':'car explodes'}}]
        c={**self.cue,'subject':'film'}
        self.assertEqual(pilot.shortlist(c,rows)[0]['id'],'a')
        c.update(narration='car explodes',purpose='explosion',required=['car explodes'])
        self.assertEqual(pilot.shortlist(c,rows)[0]['id'],'b')

    def test_cache_avoids_repeat_request_and_budget_is_hard(self):
        with tempfile.TemporaryDirectory() as d:
            work=Path(d)/'run'
            work.mkdir()
            result={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}],
                    'usageMetadata':{'totalTokenCount':10}}
            with patch.object(pilot,'api_call',return_value=result) as call:
                m=pilot.Model(work,'fake',1)
                self.assertTrue(m.ask('test','hello')['ok'])
                self.assertTrue(m.ask('test','hello')['ok'])
                self.assertEqual(call.call_count,1)
                with self.assertRaises(ValueError):
                    m.ask('test','changed')

    def test_render_filter_handles_literal_untrusted_text(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(self.cue)
            c['edit'].update(preset='title',text="%{evil} ' : \\ text")
            vf=edit_pilot.filters(Path(d),{'start':5.,'end':15.},[c])
            self.assertIn('expansion=none',vf)
            self.assertNotIn('%{evil}',vf)


if __name__=='__main__':
    unittest.main()
