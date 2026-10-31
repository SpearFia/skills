# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stage3_index import Indexer
from stage3_resume import BudgetIndexer,freeze_check,spaced


class ResumeTest(unittest.TestCase):
    def test_source_cap_overlap_and_lifting(self):
        index=BudgetIndexer.__new__(BudgetIndexer)
        index.targets={'need':90}
        index.relaxed=set()
        index.phase='initial'
        index.candidates=[dict(need_id='need',video_id='a',start=0,end=60,purpose='main',passed=True),
            dict(need_id='need',video_id='a',start=30,end=90,purpose='main',passed=True)]
        self.assertEqual(index.credit('need'),30)
        self.assertEqual(index.remaining('need','a'),0)
        self.assertEqual(index.remaining('need','b'),30)
        index.relaxed={'need'}
        self.assertEqual(index.credit('need'),90)
        self.assertEqual(index.remaining('need','b'),0)

    def test_refill_uses_matching_sources_only(self):
        index=BudgetIndexer.__new__(BudgetIndexer)
        index.targets={'need':90}
        index.relaxed={'need'}
        index.phase='quota_refill'
        index.candidates=[dict(need_id='need',video_id='a',start=0,end=10,purpose='main',passed=True)]
        self.assertEqual(index.active(dict(id='a',needs=['need'])),['need'])
        self.assertEqual(index.active(dict(id='b',needs=['need'])),[])
        index.phase='variants'
        self.assertEqual(index.active(dict(id='b',needs=['need'])),['need'])

    def test_spacing_and_frozen_source_guard(self):
        self.assertFalse(spaced(12,24,[dict(start=0,end=12)]))
        self.assertTrue(spaced(24,36,[dict(start=0,end=12)]))
        index=BudgetIndexer.__new__(BudgetIndexer)
        index.frozen={'done'}
        with self.assertRaisesRegex(ValueError,'immutable'):
            index.predict(dict(id='done'),0,1,2,[])

    def test_main_query_is_separate_from_fallback_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            index=BudgetIndexer.__new__(BudgetIndexer)
            index.needs={'need':dict(query='A man runs.',variants=['A person runs.'])}
            index.query_mode='main'
            index.windows=[]
            index.settings=dict(fps=[.2,.5,2.])
            index.events=Path(directory)
            index.sampled_windows={'video':[]}
            index.db=sqlite3.connect(':memory:')
            index.db.execute('CREATE TABLE scores(video_id,query_hash,round,t0,t1,p,window_id)')
            captured=[]
            def predict(video,a,b,fps,questions):
                captured.extend(q['query'] for q in questions)
                index.last_sample=dict(path='clip.mp4',start=a,end=b,video_id='video',fps=fps)
                return 'task',dict(record=dict(frames=4,score_bounds=[[0,.75],[.75,2]]),
                    queries=[dict(question=q,output=dict(probabilities=[.8,.8])) for q in questions])
            index.predict=predict
            window=dict(start=0,end=2,needs=['need'])
            index.score_window(dict(id='video'),window,3,[])
            self.assertEqual(captured,['A man runs.'])
            index.query_mode='variants'
            index.score_window(dict(id='video'),window,3,[])
            self.assertEqual(captured,['A man runs.','A person runs.'])
            self.assertEqual(index.needs['need']['variants'],['A person runs.'])
            index.db.close()

    def test_confirmation_cuts_from_the_existing_round3_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            index=Indexer.__new__(Indexer)
            index.cache=root
            index.tasks=root/'tasks'
            index.tasks.mkdir()
            index.config=dict(model={})
            index.timings=[]
            proxy=root/'proxy.mp4'
            proxy.write_bytes(b'proxy')
            fine=root/'fine.mp4'
            fine.write_bytes(b'fine')
            calls=[]
            def cut(args,timeout):
                calls.append(args)
                Path(args[-1]).write_bytes(b'cut')
            def complete():
                request=next(index.tasks.glob('*.request.json'))
                task=json.loads(request.read_text())
                result=dict(status='complete',prepare_seconds=0,encode_seconds=0,wall_seconds=0,
                    queries=[dict(question=q,seconds=0,peak_allocated_mib=0,peak_reserved_mib=0) for q in task['questions']])
                request.with_name(request.name.replace('.request.json','.result.json')).write_text(json.dumps(result))
            index.check_worker=complete
            with patch('stage3_index.command',side_effect=cut):
                index.predict(dict(id='video',path=str(proxy),crop=dict(w=100,h=100,x=0,y=0)),105,110,2.,
                    [dict(id='need',task='choice',query='What?',options=['A','B'])],sample_from=dict(path=str(fine),start=100,end=120))
            self.assertEqual(calls[0][calls[0].index('-i')+1],str(fine))
            self.assertEqual(calls[0][calls[0].index('-ss')+1],'5.000000')
            self.assertNotIn('crop=',calls[0][calls[0].index('-vf')+1])
            self.assertIn('wait_overhead_seconds',index.timings[0])

    def test_ffmpeg_frozen_check_without_full_clip_qc(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            for source,expected in [('color=black:size=128x72:rate=2',True),('testsrc2=size=128x72:rate=2',False)]:
                path=Path(directory)/('still.mp4' if expected else 'moving.mp4')
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',source,'-t','3','-c:v','libx264','-threads','1',str(path)],check=True)
                self.assertEqual(freeze_check(path,3)['frozen'],expected)


if __name__=='__main__':
    unittest.main()
