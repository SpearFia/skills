# SPDX-License-Identifier: MIT OR Apache-2.0
import collections
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from script_first import key,read
from stage3_sources import save_json
from stage4_build import TICKS,ticks
from stage5_check import comparison_html,references
from stage5_edit import NewQuery,choose_exact,edit,resolve_need,seconds,slot_at,source_spans,visible


class Stage5Tests(unittest.TestCase):
    def test_comparison_identifies_separate_tests_and_does_not_equate_saved_with_visual_pass(self):
        rows=[dict(mode='fill',test='cached fill',at='2698.266667-2702.133333',input_label='your saved edit (column 2)',videos=['0-a.mp4','0-b.mp4','0-c.mp4']),
            dict(mode='swap',test='cached swap',at='0.01666666666666',input_label='the original automatic review (column 1)',videos=['2-a.mp4','2-b.mp4','2-c.mp4'])]
        page=comparison_html(rows,[dict(test='new-query fill',status='unfilled',reason='No unused match')],{'cached fill':dict(note='Rejected <bad shot>')})
        for text in ['Each row is a separate test','Fill gap at 44:58.267–45:02.133','Swap shot at 00:00.017','your saved edit (column 2)',
            'the original automatic review (column 1)','No comparison row: new-query fill','Rejected &lt;bad shot&gt;']:
            self.assertIn(text,page)
        self.assertEqual(page.count('<video '),6)
        replaced=comparison_html(rows,[],{'cached fill':dict(note='Old rejected output',output='another.fcproj')})
        self.assertNotIn('Old rejected output',replaced)

    def test_timestamps_and_rejected_input(self):
        self.assertEqual(seconds('1:02:03.5'),3723.5)
        self.assertEqual(seconds('12:03'),723)
        for text in ['nan','inf','-1','1:60','1:2:3:4','']:
            with self.subTest(text=text),self.assertRaises(ValueError):seconds(text)
        with self.assertRaises(ValueError):edit(Path('not-read'),Path('not-read'),'fill','0-2',need='x',query='y')

    def test_visibility_prioritizes_enabled_top_track(self):
        def clip(i,a,b):return dict(id=i,start=a,duration=b-a,enabled=True)
        spans=visible([dict(enabled=True,items=[clip(1,0,10)]),dict(enabled=True,items=[clip(2,3,6)]),dict(enabled=False,items=[clip(3,0,10)])])
        self.assertEqual([(a,b,c['id']) for a,b,c in spans],[(0,3,1),(3,6,2),(6,10,1)])

    def test_fill_rejects_occupied_range_and_swap_requires_picture(self):
        tracks=[dict(enabled=True,items=[dict(id=1,start=ticks(30),duration=ticks(60),enabled=True)])]
        with patch('stage5_edit.footage_tracks',return_value=tracks):
            slot,removed=slot_at(None,None,'fill','3-4');self.assertEqual(slot['start_frame'],90);self.assertIsNone(removed)
            with self.assertRaisesRegex(ValueError,'overlaps'):slot_at(None,None,'fill','0-2')
            with self.assertRaisesRegex(ValueError,'No visible'):slot_at(None,None,'swap','4')
            slot,removed=slot_at(None,None,'swap','2');self.assertEqual((slot['start_frame'],slot['duration_frames'],removed['id']),(30,60,1))

    def test_source_mapping_respects_trim_and_hidden_alternates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);file=p/'B-roll/master.mp4';m=dict(file='B-roll/master.mp4',video_id='v',start=100,end=120)
            save_json(p/'media/jev/script-first/stage4/masters.json',[m])
            data=dict(project=dict(items={'9':dict(kind=dict(Media=dict(media=dict(File=dict(path=str(file))))))}))
            low=dict(id=1,item=9,start=0,duration=4*TICKS,source_in=2*TICKS,enabled=True,reverse=False,speed=1)
            top=dict(low,id=2,start=TICKS,duration=2*TICKS,source_in=8*TICKS)
            rows=source_spans(p,data,[dict(enabled=True,items=[low]),dict(enabled=True,items=[top])])
            self.assertEqual([(r['start'],r['end']) for r in rows],[(102,103),(108,110),(105,106)])
            low['speed']=.5;top['speed']=2
            rows=source_spans(p,data,[dict(enabled=True,items=[low]),dict(enabled=True,items=[top])])
            self.assertEqual([(r['start'],r['end']) for r in rows],[(102,102.5),(108,112),(103.5,104)])
            self.assertEqual([(r['timeline'],r['end_time']) for r in rows],[(0,1),(1,3),(3,4)])
            self.assertEqual(low['speed'],.5);self.assertEqual(top['speed'],2)

    def test_invalid_speeds_and_unmapped_retiming_fail_before_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);file=p/'master.mp4';save_json(p/'media/jev/script-first/stage4/masters.json',[dict(file='master.mp4',video_id='v',start=0,end=20)])
            data=dict(project=dict(items={'9':dict(kind=dict(Media=dict(media=dict(File=dict(path=str(file))))))}))
            clip=dict(id=1,item=9,start=0,duration=TICKS,source_in=0,enabled=True,reverse=False,speed=1)
            invalid=[dict(speed=x) for x in [0,-1,float('nan'),float('inf')]]+[dict(reverse=True),dict(frame_hold=dict(source=0)),
                dict(effects=[dict(effect='time_remap',params=dict(speed=dict(value=dict(Float=50))))])]
            for extra in invalid:
                with self.subTest(extra=extra),self.assertRaises(ValueError):source_spans(p,data,[dict(enabled=True,items=[dict(clip,**extra)])])

    def test_approved_need_resolution_does_not_use_old_subject_boundaries(self):
        a=SimpleNamespace(pools={'gta5':{}},qs={'q':dict(source_group='gta5')},document=dict(visual_catalog=[]))
        self.assertEqual(resolve_need(a,'gta5')['kind'],'general')
        self.assertEqual(resolve_need(a,'q')['question_id'],'q')
        with self.assertRaisesRegex(ValueError,'approved'):resolve_need(a,'unknown-old-subject')

    def test_fill_cannot_silently_shorten_to_available_candidate(self):
        a=SimpleNamespace(proposal=lambda s:[dict(frames=30)],duplicate=lambda *args:False)
        self.assertIsNone(choose_exact(a,dict(duration_frames=60,kind='specific')))

    def test_reference_is_byte_identical_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);review=p/'sync/edited.fcproj';review.parent.mkdir();review.write_bytes(b'saved edit')
            with patch('stage5_check.approve'),patch('stage5_check.load_review'):
                refs=references(p,review);self.assertEqual(Path(refs['creator_reference']).read_bytes(),b'saved edit')
                review.write_bytes(b'newer edit');self.assertEqual(references(p,review)['creator_sha256'],refs['creator_sha256'])
                Path(refs['creator_reference']).write_bytes(b'changed reference')
                with self.assertRaisesRegex(ValueError,'reference changed'):references(p,review)

    def test_new_query_reuses_its_saved_answers_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);root=p/'media/jev/script-first';qid=key('gta5','A car moves.')
            folder=root/'stage5/queries'/qid;save_json(folder/'candidates.json',[dict(choice_pass=True)])
            a=SimpleNamespace(project=p,root=root,pools={'gta5':dict(videos=[dict(video_id='v')])},videos={'v':{}},excluded={'v':[]},qs={},by_query={},cells=collections.defaultdict(list))
            with patch('stage5_edit.pool.cache_dir',return_value=p/'cache'):
                r=NewQuery(a,'gta5','A car moves.',lambda text:None)
            with patch('stage5_edit.choose_exact',return_value={'match':True}),patch.object(r,'start_worker') as worker:
                r.apply(a,dict(question_id=qid));worker.assert_not_called()
            self.assertEqual(a.by_query[qid],[dict(choice_pass=True)]);self.assertEqual(read(folder/'query.json')['context'],32768)


if __name__=='__main__':unittest.main()
