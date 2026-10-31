# SPDX-License-Identifier: MIT OR Apache-2.0
import collections
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script_assignment import Assignment,beat_times,general_slots,make_slots
from script_first import key,read
from script_queries import saved_choices
from script_stage4 import replace_footage_links
from stage3_sources import save_json
from stage4_assign import FrameIndex,assert_no_overlap


class ScriptAssignmentTests(unittest.TestCase):
    def test_short_literal_then_general_remainder_without_old_cues(self):
        d=dict(beats=[dict(id='a',line=9,text='He enters the car, then travels.',classification='specific',
            visuals=[dict(source_group='gta6',query='A person enters a car.')])])
        proof,spans=make_slots(d,dict(a=dict(start_frame=300,end_frame=1200,vo_path='vo.wav')))
        self.assertEqual(proof[0]['duration_frames'],90)
        self.assertEqual(proof[0]['question_id'],key('gta6','A person enters a car.'))
        slots=proof+general_slots(spans)
        self.assertEqual(sum(s['duration_frames'] for s in slots),900)
        self.assertTrue(all(s['groups']==['gta6'] for s in slots))
        self.assertTrue(all(x['start_frame']+x['duration_frames']==y['start_frame'] for x,y in zip(slots,slots[1:])))

    def test_adjacent_general_sentences_merge_but_groups_and_vo_do_not(self):
        def span(a,b,group='wick1',vo='v'):return dict(start_frame=a,end_frame=b,groups=[group],vo_path=vo,beat_ids=[str(a)])
        slots=general_slots([span(0,30),span(30,60),span(60,90,'wick2'),span(90,120,'wick2','other')])
        self.assertEqual([s['duration_frames'] for s in slots],[60,30,30])
        self.assertEqual(slots[0]['beat_ids'],['0','30'])

    def test_repeated_sentence_offsets_use_ordinal_not_first_text_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'script').mkdir();(p/'script/script.md').write_text('VO: Go now. Go now.\n')
            save_json(p/'media/vo-words.json',{'v':dict(words=[['Go',0,.5],['now.',.5,1],['Go',1,1.5],['now.',1.5,2]])})
            save_json(p/'sync/plans/a.json',dict(items=[dict(kind='clip',track='A1',source=dict(path='v'),start_frame=100,duration_frames=60)]))
            d=dict(beats=[dict(id='a',line=1,sentence=1,text='Go now.'),dict(id='b',line=1,sentence=2,text='Go now.')])
            with patch('script_assignment.pool.links',return_value=[dict(role='voiceover',line=0,media=dict(path='v'))]):t=beat_times(p,d)
            self.assertEqual([(t[x]['start_frame'],t[x]['end_frame']) for x in ['a','b']],[(100,130),(130,160)])

    def test_cached_main_alias_preserves_quality_and_scope_rejections(self):
        q=dict(source_group='gta5',query='A car moves.');qs={'main':q,'variant':dict(q,query='A car stops.')}
        def visual(query,mode):return dict(source_group='gta5',query=query,saved_score_reference=dict(query_mode=mode,question=query,cache_need_id='old'))
        d=dict(visual_catalog=[visual(q['query'],'main'),visual('A car stops.','variant')])
        c=dict(id='c',video_id='v',need_id='old',start=0,end=3,options=['A. Different saved answer wording.','B. No.'],
            right_index=0,answer_index=0,probabilities=[.9,.1],passed=False)
        rows=saved_choices([c],d,qs,{('v','main'),('v','variant')},{})
        self.assertEqual([r['question_id'] for r in rows],['main']);self.assertTrue(rows[0]['choice_pass'])
        self.assertFalse(rows[0]['scene_confirmed'])
        for extra in [dict(qc_flags=['quality:logo']),dict(source_scope_status='conflict'),dict(qc=dict(frozen=True))]:
            self.assertFalse(saved_choices([dict(c,**extra)],d,qs,{('v','main')},{})[0]['choice_pass'])
        self.assertFalse(saved_choices([c],d,qs,{('v','main')},{'v':[[1,2]]}))

    def runner(self):
        a=Assignment.__new__(Assignment);a.pools={'wick1':dict(videos=[dict(video_id=v,duration=100) for v in ['a','b']])}
        a.quality={v:[[0,100]] for v in ['a','b']};a.videos={v:dict(probe=dict(duration=100,fps=30)) for v in ['a','b']}
        a.used=collections.defaultdict(list);a.rejected=collections.defaultdict(list);a.placements=collections.defaultdict(list)
        a.share=collections.Counter();a.pool_used=collections.Counter();a.cells=collections.defaultdict(list)
        a.frames={v:[] for v in ['a','b']};a.times={v:[] for v in ['a','b']};a.frame_index=FrameIndex();a.duplicates=0
        return a

    def test_general_needs_no_positive_scores_and_uses_global_ledger_spacing(self):
        a=self.runner();slot=dict(id='one',kind='general',groups=['wick1'],duration_frames=120,start_frame=300,top=None,alternates=[])
        c=a.choose(slot);a.book(slot,c);other=dict(slot,id='two',top=None,start_frame=450)
        second=a.choose(other);self.assertNotEqual(c['video_id'],second['video_id']);a.book(other,second)
        self.assertIsNone(c['score']);assert_no_overlap([slot,other])
        third=dict(slot,id='three',top=None,start_frame=600);last=a.choose(third)
        self.assertTrue(last['video_id']!=c['video_id'] or last['end']<=c['start'] or last['start']>=c['end'])

    def test_native_highest_rate_scores_and_text_black_handle_guard(self):
        a=self.runner();a.cells['q','a']=[(0,4,.99,.2),(0,2,.1,2),(2,4,.3,2)]
        self.assertAlmostEqual(a.raw_score('q','a',0,4),.2)
        a.quality['a']=[[0,10],[12,100]]
        self.assertEqual(list(a.free_ranges('a',0,100)),[[0,7.5],[14.5,100]])

    def test_coherent_visual_copy_rejected(self):
        a=self.runner();a.frames['b']=[dict(time=i,hash=str(100+int(i*2)),color=[50]*3) for i in [0,.5,1]]
        a.times['b']=[0,.5,1]
        for f in a.frames['b']:a.frame_index.add(dict(f,time=f['time']+20),'old')
        self.assertTrue(a.duplicate('b',0,1.5))

    def test_replace_links_preserves_audio_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);folder=p/'work';folder.mkdir()
            audio=dict(id='a',media=dict(path='Music/bed.mp3'));footage=dict(id='f',media=dict(path='B-roll/old.mp4'))
            original=dict(next_id=9,links=[audio,footage]);save_json(p/'links.json',original)
            replace_footage_links(p,folder);replace_footage_links(p,folder)
            self.assertEqual(read(p/'links.json'),dict(next_id=9,links=[audio]));self.assertEqual(read(folder/'links-before-script-stage4.json'),original)
            save_json(p/'links.json',dict(next_id=9,links=[]))
            with self.assertRaisesRegex(ValueError,'Non-footage'):replace_footage_links(p,folder)


if __name__=='__main__':unittest.main()
