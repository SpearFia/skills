# SPDX-License-Identifier: MIT OR Apache-2.0
"""Renderer checks use Pillow from the unchanged Windows baseline environment."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('PIL'), 'Run with the existing Pillow environment')
class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project=Path(self.temporary.name)/'project'
        self.folder=self.project/'media'/'jev'
        self.folder.mkdir(parents=True)
        fixture=Path(__file__).parent/'examples'/'cwi-003'
        self.need=json.loads((fixture/'needs.json').read_text(encoding='utf-8'))[0]
        self.inputs=json.loads((fixture/'input-cues.json').read_text(encoding='utf-8'))
        self.key=self.need['id']
        self.videos={v:dict(id=v,status='ready',needs=[self.key],title='fixture',probe=dict(duration=500)) for v in ['a','b']}
        self.plan={v:[[0,120],[120,240],[240,360]] for v in self.videos}
        self.rows=[]
        for video in self.videos:
            self.rows.append(dict(video_id=video,need_id=self.key,round=2,start=0,end=500,window_id=video+'-retained',
                audit=False,fps=.5,frames=250,black=[],bounds=[],probabilities=[]))
            for i,(a,b) in enumerate(self.plan[video]):
                self.rows.append(dict(video_id=video,need_id=self.key,round=3,start=a,end=b,window_id=video+str(i),
                    audit=True,fps=2.,frames=240,black=[],bounds=[],probabilities=[]))

    def render(self,representatives=None):
        from stage3_review import render
        (self.folder/'score-windows.json').write_text(json.dumps(self.rows))
        (self.folder/'timing-report.json').write_text('[]')
        candidate=dict(id='candidate',video_id='a',need_id=self.key,purpose='miss_audit',start=30,end=35,passed=True,
            source_scope_status='creator_group_not_independently_verified',coarse_dropped=[[30,35]],coarse_dropped_seconds=5)
        with patch('stage3_sources.pool.cache_dir',return_value=self.project/'cache'):
            render(self.project,self.videos,{self.key:self.need},self.inputs,[candidate],representatives or [],
                dict(videos=list(self.videos.values())),dict(failed_videos=[]),self.plan)
        return json.loads((self.folder/'miss-audit-report.json').read_text())

    def test_merged_retained_question_windows_do_not_become_false_misses(self):
        report=self.render()
        self.assertTrue(report['gate_complete'])
        self.assertEqual(report['audited_sources'],2)
        self.assertEqual(report['coarse_missed_candidate_spans'],0)

    def test_planned_but_incomplete_source_is_not_an_audited_source(self):
        self.rows=[r for r in self.rows if r['window_id']!='b2']
        report=self.render()
        self.assertFalse(report['gate_complete'])
        self.assertEqual(report['audited_sources'],1)

    def test_hard_example_cannot_be_reported_without_choice_results(self):
        self.need['hard']=True
        with self.assertRaisesRegex(ValueError,'complete choice result'):
            self.render([dict(need_id=self.key)])


if __name__=='__main__':
    unittest.main()
