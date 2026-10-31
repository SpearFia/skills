# SPDX-License-Identifier: MIT OR Apache-2.0
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script_first import key
from stage3_sources import save_json


@unittest.skipUnless(importlib.util.find_spec('PIL'),'Pillow renderer environment')
class QueryReviewTest(unittest.TestCase):
    def test_review_includes_random_near_miss_and_choice_context(self):
        from PIL import Image
        from script_query_review import render
        q='A police helicopter flies above city streets.';qid=key('gta5',q)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);root=p/'media/jev/script-first';f=root/'query-results'
            beat=dict(id='b1',classification='specific',visuals=[dict(id='v1',source_group='gta5',query=q,manual=False,scene=None)])
            save_json(root/'beats.json',dict(counts=dict(sentences=1),beats=[beat]))
            choice=dict(id='c',question_id=qid,need_id=qid,video_id='video',start=10,end=12,purpose='main',options=['A. '+q,'B. Not visible.','C. Unclear.'],probabilities=[.8,.1,.1],right_index=0,answer_index=0,confirmation=.8,choice_pass=True,source_scope_status='creator_group_not_independently_verified')
            representative=dict(question_id=qid,need_id=qid,video_id='video',start=10,end=11,probability=.7,round=3,threshold=.5,kind='random above threshold',choice=choice)
            save_json(f/'cached-choices.json',[]);save_json(f/'candidates.json',[choice]);save_json(f/'representatives.json',[representative,dict(representative,kind='near miss below threshold',probability=.49)])
            save_json(f/'miss-audit.json',dict(sources=[dict(video_id='video')],dropped_matches=[]))
            save_json(root/'score-reuse.json',dict(rows=[]));save_json(f/'score-windows.json',[dict(question_id=qid,probabilities=[.7],black=[False])])
            save_json(p/'media/jev/download-report.json',dict(videos=[dict(id='video',status='ready',title='Synthetic',path='unused',crop=None)]))
            (p/'production').mkdir()
            with patch('stage3_review.thumbnail',return_value=Image.new('RGB',(320,180),'orange')):render(p)
            page=(p/'production/jev-script-query-review/review.html').read_text(encoding='utf8')
            self.assertIn('Named scenes and identities require creator review',page)
            self.assertTrue(list((p/'production/jev-script-query-review').glob('*.jpg')))
            result=json.loads((f/'coverage.json').read_text());self.assertFalse(result['assignment_started']);self.assertFalse(result['stage5'])
            self.assertEqual(result['hard_needs'][0]['displayed_choices'],2)


if __name__=='__main__':unittest.main()
