# SPDX-License-Identifier: MIT OR Apache-2.0
import unittest
import hashlib
import json
import tempfile
import sqlite3
from pathlib import Path

from stage3_index import Indexer, merge_windows, runs, scope_status, subtract, union
from stage3_sources import download, prepare_project


class Stage3Test(unittest.TestCase):
    def test_negative_and_black_cells_never_make_candidates(self):
        bounds = [[0,1],[1,2],[2,3],[3,4],[4,5]]
        self.assertEqual(runs([.1]*5,bounds,.5,40,[False]*5),[])
        spans = runs([.8,.8,.9,.8,.8],bounds,.5,40,[False,False,True,False,False])
        self.assertEqual([(s['start'],s['end']) for s in spans],[(40,42),(43,45)])
        spans = runs([.8,.1,.8,.1,.1],bounds,.5,40,[False]*5)
        self.assertEqual([(s['start'],s['end']) for s in spans],[(40,43)])
        with self.assertRaises(ValueError):
            runs([float('nan')],[[0,1]],.5,0,[False])

    def test_padding_question_union_and_frame_safe_splitting(self):
        windows = [dict(start=-10,end=30,needs=['a']),dict(start=20,end=200,needs=['b'])]
        result = merge_windows(windows,180,120)
        self.assertEqual(result,[dict(start=0,end=120,needs=['a','b']),dict(start=120,end=180,needs=['a','b'])])
        self.assertTrue(all((w['end']-w['start'])*2 <= 2048 for w in result))

    def test_black_subtraction_and_miss_check_include_coarse_padding(self):
        self.assertEqual(union([[10,20],[18,30],[35,36]]),[[10,30],[35,36]])
        self.assertEqual(subtract(8,38,[[10,20],[18,30],[35,36]]),[[8,10],[30,35],[36,38]])
        # The raw coarse hit is 20..30, but its retained padded range is 10..40.
        self.assertEqual(subtract(12,18,[[10,40]]),[])
        self.assertEqual(subtract(38,45,[[10,40]]),[[40,45]])

    def test_wrong_film_is_a_scope_conflict_without_retagging_input(self):
        video=dict(title='John Wick: Chapter 4 (2023) - Top-Down Shootout Scene')
        self.assertEqual(scope_status(video,dict(source_group='wick1')),'conflict')
        self.assertEqual(scope_status(video,dict(source_group='wick4')),'title_matches_group')
        self.assertEqual(scope_status(dict(title="John Wick Franchise's Best Scenes"),dict(source_group='wick2')),'mixed_films_review_required')

    def test_copy_preserves_checklist_cards_audio_and_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original,project=root/'original',root/'demo'
            for relative in ['script/script.md','visuals/visuals.md','B-roll/old.mp4','A-roll/vo.wav','Music/bed.wav','media/card.png']:
                path=original/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'original')
            links=dict(links=[dict(media=dict(path='B-roll/old.mp4')),dict(media=dict(path='A-roll/vo.wav')),dict(media=dict(path='media/card.png'))])
            (original/'links.json').write_text(json.dumps(links))
            folder=project/'media'/'jev'
            folder.mkdir(parents=True)
            inputs=dict(source_project=str(original),script_sha256=hashlib.sha256(b'original').hexdigest(),visuals_sha256=hashlib.sha256(b'original').hexdigest(),
                cues=[dict(id='cue',subject='Film',match='subject')])
            needs=[dict(id='wick1-action',label='Action',query='A man runs.',source_group='wick1',source_scope='Film',cues=['cue'],generic=True,fallback=None,
                confirm=dict(question='What is visible?',right='A man runs.',wrong=['A car.','A room.']))]
            (folder/'input-cues.json').write_text(json.dumps(inputs))
            (folder/'needs.json').write_text(json.dumps(needs))
            checklist=project/'production'/'media-checklist.md'
            checklist.parent.mkdir()
            submitted='## group-wick1: John Wick 1\nhttps://youtu.be/AbCdEf12345\n'
            checklist.write_text(submitted)
            videos=prepare_project(project)
            self.assertEqual(videos[0]['needs'],['wick1-action'])
            self.assertEqual(checklist.read_text(),submitted)
            self.assertFalse((project/'B-roll').exists())
            self.assertEqual(len(json.loads((project/'links.json').read_text())['links']),2)
            self.assertEqual((project/'media/card.png').read_bytes(),b'original')
            self.assertEqual((original/'links.json').read_text(),json.dumps(links))
            self.assertEqual(prepare_project(project),videos)
            proxy=root/'proxy.mp4'
            proxy.write_bytes(b'cached')
            cached=folder/'downloads'/'AbCdEf12345.json'
            cached.parent.mkdir()
            cached.write_text(json.dumps(dict(status='ready',path=str(proxy),needs=['old-question'])))
            self.assertEqual(download(videos[0],root,folder)['needs'],['wick1-action'])

    def test_sparse_mp4_tail_does_not_extend_source_score_bounds(self):
        index=Indexer.__new__(Indexer)
        index.settings=dict(fps=[.2,.5,2.])
        index.needs={'action':dict(query='A man runs.')}
        index.windows=[]
        index.db=sqlite3.connect(':memory:')
        index.db.execute('CREATE TABLE scores(video_id,query_hash,round,t0,t1,p,window_id)')
        result=dict(record=dict(score_bounds=[[0,5]],frames=1),queries=[dict(question=dict(id='action-v0'),output=dict(probabilities=[.9]))])
        index.predict=lambda *args:('task',result)
        window=dict(start=100.,end=102.1,needs=['action'])
        for _ in range(2):
            rows=index.score_window(dict(id='video'),window,1,[])
        self.assertAlmostEqual(rows[0]['start']+rows[0]['bounds'][0][1],102.1)
        stored=index.db.execute('SELECT t0,t1 FROM scores').fetchall()
        self.assertEqual(len(stored),1)
        self.assertAlmostEqual(stored[0][1],102.1)
        index.db.close()


if __name__ == '__main__':
    unittest.main()
