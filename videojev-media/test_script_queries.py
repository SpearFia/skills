# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script_queries import ScriptQueries,candidate_spans,choice_question,confirmation_parent,retained,safe_context,spaced_examples
from stage3_index import Indexer
from stage3_sources import save_json


class ScriptQueryTests(unittest.TestCase):
    def runner(self,p):
        r=ScriptQueries.__new__(ScriptQueries);r.allowed={('video','a'),('video','b'),('video','c')}
        r.qs={'a':dict(query='A car moves.'),'b':dict(query='A car moves.'),'c':dict(query='A helicopter flies.')}
        r.lookup={};r.worker=object();r.tasks=p/'tasks';r.tasks.mkdir();r.folder=p;r.timings=[];r.state={}
        r.config=dict(model=dict(revision='pinned-test'))
        r.status=lambda phase:None
        return r

    def test_per_question_reuse_and_identical_physical_questions_are_not_sent_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);proxy=p/'proxy.mp4';proxy.write_bytes(b'proxy');r=self.runner(p);calls=[]
            def predict(self,video,a,b,fps,questions,sample_from=None):
                calls.append(questions);task='task'+str(len(calls));self.last_sample=dict(path=str(proxy),start=a,end=b,video_id='video',fps=fps)
                result=dict(status='complete',record=dict(frames=4,score_bounds=[[0,1],[1,2]]),queries=[
                    dict(question=q,output=dict(id=q['id'],probabilities=[.3,.8])) for q in questions])
                save_json(self.tasks/(task+'.result.json'),result);return task,result
            video=dict(id='video',path=str(proxy),crop=None)
            a=dict(id='a-v0',task='grounding',query='A car moves.');b=dict(a,id='b-v0');c=dict(id='c-v0',task='grounding',query='A helicopter flies.')
            with patch.object(Indexer,'predict',predict):
                first=r.predictions(video,0,2,2,[a,b]);self.assertEqual(len(first),2)
                self.assertEqual(len(calls),1);self.assertEqual(len(calls[0]),1)
                second=r.predictions(video,0,2,2,[a,c]);self.assertEqual(len(second),2)
                self.assertEqual(calls[1],[c])
                r.predictions(video,0,2,2,[b]);self.assertEqual(len(calls),2)
            stored=json.loads((r.tasks/'task1.result.json').read_text());self.assertEqual(stored['queries'][0]['question']['id'],'a-v0')

    def test_cached_or_unapproved_pairs_and_changed_text_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.runner(Path(tmp));video=dict(id='video',path='not-read')
            for q in [dict(id='old-v0',task='grounding',query='A car moves.'),
                dict(id='a-v0',task='grounding',query='A tank appears.'),
                dict(id='a-v0',task='other',query='A car moves.'),
                dict(id='a-choice',task='choice',query='Who wins?',options=[])]:
                with self.subTest(q=q),self.assertRaises(ValueError):r.predictions(video,0,2,2,[q])
            choice=choice_question('a','A car moves.','video',0,2)
            self.assertTrue(any(v.endswith('A car moves.') for v in choice['options']))
            self.assertEqual(choice,choice_question('a','A car moves.','video',0,2))

    def test_confirmation_uses_shuffled_target_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.runner(Path(tmp));r.candidates=[]
            def predict(video,a,b,fps,wanted,parent=None):
                options=wanted[0]['options'];right=next(i for i,v in enumerate(options) if v.endswith('A car moves.'))
                probs=[.1]*3;probs[right]=.8
                return [dict(answer=dict(output=dict(answer_index=right,probabilities=probs)))]
            r.predictions=predict
            result=r.confirm(dict(id='video'),'a',dict(start=0,end=2,grounding=.9),'main')
            self.assertTrue(result['choice_pass']);self.assertEqual(result['confirmation'],.8)
            self.assertTrue(result['options'][result['right_index']].endswith('A car moves.'))

    def test_only_containing_two_fps_parent_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'sample.mp4';p.write_bytes(b'fake')
            parent=dict(path=str(p),start=10,end=20,fps=2)
            self.assertIs(confirmation_parent(parent,11,13),parent)
            self.assertIsNone(confirmation_parent(dict(parent,fps=.2),11,13))
            self.assertIsNone(confirmation_parent(parent,9,13))
            self.assertEqual(safe_context(.75,1,2,[[0,.5]]),(.5,2.))
            self.assertIsNone(safe_context(.75,1,1.2,[[0,.5]]))

    def test_black_text_exclusions_and_spaced_confirmation_samples(self):
        rows=[dict(start=100,bounds=[[i,i+1] for i in range(12)],probabilities=[.9]*12,black=[False]*12)]
        spans=candidate_spans(rows,[[103,104]])
        self.assertEqual([(s['start'],s['end']) for s in spans],[(100,103),(104,112)])
        self.assertEqual(len(spaced_examples(spans)),1)
        settings=dict(thresholds=[.2,.3,.5],padding_seconds=[10,4,2])
        rows[0].update(question_id='a');kept=retained(rows,1,600,settings)
        self.assertEqual(kept[0],dict(start=90,end=122,needs=['a']))

    def test_round_two_bypass_is_per_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ScriptQueries.__new__(ScriptQueries);r.folder=Path(tmp);r.coarse={};r.excluded={'v':[]}
            r.settings=dict(window_seconds=[1800,600,120],thresholds=[.2,.3,.5],padding_seconds=[10,4,2])
            r.state=dict(profiles=[],completed_videos=[],failed_videos=[]);r.checkpoint=lambda:None;calls=[]
            def score(video,w,number):
                calls.append((number,w['needs']))
                if number==1:
                    return [dict(question_id=q,start=0,bounds=[[i*50,(i+1)*50] for i in range(12)],black=[False]*12,
                        probabilities=[.9]*12 if q=='a' else [.9,.9]+[0]*10) for q in w['needs']]
                return [dict(question_id=q,start=w['start'],bounds=[[0,w['end']-w['start']]],black=[False],probabilities=[0.]) for q in w['needs']]
            r.score=score;r.process(dict(id='v',probe=dict(duration=600)),['a','b'])
            self.assertTrue(any(n==2 for n,qs in calls));self.assertTrue(all('a' not in qs for n,qs in calls if n==2))
            self.assertEqual(sum(n==3 for n,qs in calls),5)


if __name__=='__main__':unittest.main()
