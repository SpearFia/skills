# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small safety checks for global assignment and handled masters."""
import collections
import unittest
from stage4_assign import Assignment,FrameIndex,assert_no_overlap,merge_masters,norm


class Stage4Tests(unittest.TestCase):
    def test_no_repeat_including_compilation_alias(self):
        def slot(video,start,end,canonical='scene',offset=0):
            return dict(top=dict(video_id=video,start=start,end=end,canonical_id=canonical,
                canonical_start=start+offset,canonical_end=end+offset))
        assert_no_overlap([slot('a',0,4),slot('b',104,108,offset=-100)])
        with self.assertRaises(AssertionError):
            assert_no_overlap([slot('a',0,4),slot('b',102,106,offset=-100)])

    def test_brief_action_does_not_expand_to_narration(self):
        a=Assignment.__new__(Assignment)
        a.cues={'c':dict(id='c',line=8,quote='gets into the car',match='subject')}
        a.needs={'gta6-enter-car':dict(cues=['c'],source_group='gta6')}
        a.timing={'c':dict(start_frame=100,end_frame=1000,vo_path='vo.wav')};a.slots=[]
        a.build_slots()
        self.assertEqual(sum(s['duration_frames'] for s in a.slots if s['kind']=='brief action'),90)
        self.assertEqual(sum(s['duration_frames'] for s in a.slots),900)
        self.assertEqual(a.slots[0]['start_frame'],100)
        self.assertTrue(a.slots[0]['strict'])
        self.assertTrue(all(not s['strict'] for s in a.slots if s['kind']=='illustrative remainder'))
        self.assertTrue(all(x['start_frame']+x['duration_frames']==y['start_frame'] for x,y in zip(a.slots,a.slots[1:])))
        self.assertTrue(all(s['duration_frames']<=120 for s in a.slots))

    def test_spacing_and_strict_fallback(self):
        a=Assignment.__new__(Assignment)
        a.needs={'wick1-action':dict(source_group='wick1',fallback=None)}
        a.pool={'wick1-action':[dict(video_id=v,canonical_id=v,canonical_offset=0,start=0,end=20,score=score,source_group='wick1')
                                  for v,score in [('a',.99),('b',.8)]]}
        a.used=collections.defaultdict(list);a.used_raw=collections.defaultdict(list)
        a.valid={'a':[[0,20]],'b':[[0,20]]};a.videos={v:dict(probe=dict(duration=20)) for v in ['a','b']}
        a.placements=collections.defaultdict(list,{'a':[300]});a.share=collections.Counter()
        slot=dict(need_id='wick1-action',strict=False,duration_frames=120,start_frame=600)
        conversation=dict(a.pool['wick1-action'][0],evidence_need='wick1-police-visit',score=1.)
        a.pool['wick1-action'].insert(0,conversation)
        self.assertNotIn(conversation,a.candidate_pool('wick1-action'))
        aftermath=dict(a.pool['wick1-action'][1],canonical_id='4S8_1PIolnY',score=1.)
        a.pool['wick1-action'].insert(0,aftermath)
        self.assertNotIn(aftermath,a.candidate_pool('wick1-action'))
        self.assertEqual(a.choices(slot)[0][4]['video_id'],'b')
        a.placements['b']=[300]
        self.assertTrue(a.choices(slot))  # spacing relaxes only when needed
        a.needs['wick1-police-visit']=dict(source_group='wick1',fallback='wick1-action')
        a.pool['wick1-police-visit']=[];slot.update(need_id='wick1-police-visit',strict=True)
        self.assertEqual(a.choices(slot),[])
        slot['strict']=False
        self.assertTrue(a.choices(slot))
        armor=dict(a.pool['wick1-action'][-1],source_group='wick3',evidence_need='wick3-armored-defense',exact_rejected=True)
        a.needs['wick3-armored-defense']=dict(source_group='wick3',fallback=None)
        a.needs['wick3-action']=dict(source_group='wick3',fallback=None)
        a.pool['wick3-armored-defense']=[armor];a.pool['wick3-action']=[armor]
        self.assertEqual(a.candidate_pool('wick3-armored-defense'),[])
        self.assertEqual(a.candidate_pool('wick3-action'),[armor])

    def test_merge_clamp_and_limit(self):
        videos={'v':dict(probe=dict(duration=300,width=854,height=480))}
        slots=[dict(top=dict(video_id='v',start=a,end=b),alternates=[]) for a,b in [(0,4),(8,12),(120,124),(230,234)]]
        masters=merge_masters(dict(slots=slots),videos)
        self.assertEqual(masters[0]['start'],0)
        self.assertEqual(masters[0]['end'],14.5)
        self.assertTrue(all(m['end']-m['start']<=120 for m in masters))
        dense=[dict(top=dict(video_id='v',start=a,end=a+4),alternates=[]) for a in range(10,230,6)]
        bounded=merge_masters(dict(slots=dense),videos)
        self.assertGreater(len(bounded),1)
        self.assertTrue(all(m['end']-m['start']<=120 for m in bounded))

    def test_normalization_and_frame_matching(self):
        self.assertEqual(norm('VI!'),norm('6'))
        i=FrameIndex();f=dict(hash=str(0x123456),time=1,color=[100,90,80]);i.add(f,'a')
        self.assertEqual(i.matches(dict(f,time=8))[0][2],'a')
        self.assertFalse(i.matches(f,exclude='a'))
        self.assertFalse(i.matches(dict(f,color=[200,200,200])))


if __name__=='__main__':unittest.main()
