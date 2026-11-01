# SPDX-License-Identifier: MIT OR Apache-2.0
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script_first import creator_exclusions,read
from script_outros import describe,matches,record_failure,scan,tail_start
from stage3_sources import save_json


def card(at,noise=0):
    rgb=bytearray()
    for y in range(16):
        for x in range(17):
            color=(8,8,8) if x<8 else (8,70+y,180+x)
            if 2<=x<=5 and 6<=y<=8:color=(230,230,230)
            rgb.extend(min(255,c+noise) for c in color)
    return describe(bytes(rgb),at)


class OutroTests(unittest.TestCase):
    def test_blue_black_template_matches_layout_and_not_dark_or_full_blue_footage(self):
        anchors=[card(90)]
        self.assertTrue(matches(card(90.5,noise=2),anchors))
        self.assertFalse(matches(describe(bytes([5,5,5])*272,0),anchors))
        self.assertFalse(matches(describe(bytes([8,70,190])*272,0),anchors))
        different=card(91);different['hash']^=(1<<256)-1
        self.assertFalse(matches(different,anchors))

    def test_outro_needs_a_contiguous_run_and_pads_the_detected_boundary(self):
        anchors=[card(0)]
        self.assertEqual(tail_start([card(90),card(90.5),card(91)],anchors),89.5)
        self.assertIsNone(tail_start([card(90),card(91),card(91.5)],anchors))
        self.assertIsNone(tail_start([card(90),describe(bytes([0])*816,90.5),card(91)],anchors))

    def setup_sources(self,p):
        seed=p/'seed.mp4';seed.write_bytes(b'proxy')
        videos=[dict(id=v,status='ready',channel_id=channel,path=str(seed),crop=None,probe=dict(duration=100)) for v,channel in [('seed','movieclips'),('second','movieclips'),('other','other-channel')]]
        save_json(p/'media/jev/download-report.json',dict(videos=videos))
        return dict(slot=dict(id='edit',start_frame=30,top=dict(video_id='seed',source_group='wick4',start=90,end=94)),output=str(p/'review.fcproj'))

    def test_same_channel_scan_and_control_guard_preserve_existing_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);result=self.setup_sources(p);folder=p/'scan'
            def sample(video,start,end):
                return [card(90),card(90.5),card(91)] if end>80 else [describe(bytes([5])*816,start)]
            with patch('script_outros.samples',side_effect=sample):report,_,_=scan(p,result,folder,lambda phase:None)
            self.assertEqual({e['video_id'] for e in report['entries']},{'seed','second'})
            self.assertEqual(report['control_matches'],0)
            path=p/'media/jev/script-first/outro-scans.json';before=path.read_bytes()
            self.assertEqual(creator_exclusions(p),{'seed':[[89.5,100]],'second':[[89.5,100]]})
            with patch('script_outros.samples',return_value=[card(90),card(90.5),card(91)]):
                with self.assertRaisesRegex(ValueError,'interior control'):scan(p,result,p/'bad-controls',lambda phase:None)
            self.assertEqual(path.read_bytes(),before)

    def test_stage5_failure_registration_is_idempotent_and_separate_from_automatic_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);result=self.setup_sources(p);path=p/'media/jev/script-first/creator-rejections.json';save_json(path,dict(version=1,entries=[]))
            record_failure(p,result,'black left, blue waves right');record_failure(p,result,'black left, blue waves right')
            self.assertEqual(len(read(path)['entries']),1)
            self.assertEqual(read(path)['entries'][0]['confirmed_shot'],[90,94])
            self.assertEqual(creator_exclusions(p),{'seed':[[90,100]]})


if __name__=='__main__':unittest.main()
