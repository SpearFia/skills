# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev import require_legacy
from script_first import approve,cached_scores,checklist_sources,choose_general,general_pools,key,questions,render_checklist,validate_beats
from script_text_screens import WindowsOcr,flat_share,is_text_screen,scan_video


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf8')


class ScriptFirstTests(unittest.TestCase):
    def document(self):
        general=dict(source_group='wick1',query=None,manual=False)
        specific=dict(id='v1',source_group='gta5',query='A car moves.',manual=False,scene=None)
        return dict(counts=dict(sentences=3),beats=[dict(id='b1',line=1,text='He can win.',classification='general',visuals=[general]),
            dict(id='b2',line=2,text='A car.',classification='specific',visuals=[specific]),
            dict(id='b3',line=3,text='A car again.',classification='specific',visuals=[copy.deepcopy(specific)])],visual_catalog=[specific])

    def test_only_specific_questions_and_immutable_approval(self):
        d=self.document();validate_beats(d);self.assertEqual(len(questions(d)),1)
        d['beats'][0]['visuals'][0]['query']='A fight.'
        with self.assertRaisesRegex(ValueError,'no query'):validate_beats(d)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'original';demo=root/'demo';script=b'VO: He can win.\n'
            for p in [original,demo]:(p/'script').mkdir(parents=True);(p/'script/script.md').write_bytes(script)
            d=self.document();d.update(approved_script=str(original/'script/script.md'),approved_script_sha256=hashlib.sha256(script).hexdigest())
            draft=demo/'media/jev/script-beats-draft.json';write(draft,d)
            approve(demo);f=demo/'media/jev/script-first/beats.json';self.assertEqual(json.loads(f.read_text()),d)
            d['beats'][0]['text']='Changed.';write(draft,d)
            with self.assertRaisesRegex(ValueError,'draft changed'):approve(demo)
            with self.assertRaisesRegex(ValueError,'disabled'):require_legacy(demo)

    def test_native_scores_not_legacy_variant_maxima(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);p=cache/'tasks/a.result.json'
            write(p,dict(status='complete',context=32768,record=dict(frames=4,score_bounds=[[0,1],[1,2]]),queries=[
                dict(question=dict(id='old-v0',task='grounding',query='A car moves.'),output=dict(probabilities=[.1,.3])),
                dict(question=dict(id='old-v1',task='grounding',query='A helicopter flies.'),output=dict(probabilities=[.9,.99]))]))
            q=next(iter(questions(self.document()).values()));qs={q['id']:q}
            windows=[dict(window_id='a',video_id='v',start=0,end=2,fps=2,black=[False,False],probabilities=[.9,.99])]
            rows,missing=cached_scores(cache,windows,qs,{q['id']:{'v'}})
            self.assertEqual(rows[0]['probabilities'],[.1,.3]);self.assertFalse(rows[0]['scene_confirmed']);self.assertEqual(missing,0)
            rows,_=cached_scores(cache,windows,qs,{q['id']:{'other'}});self.assertEqual(rows,[])

    def test_checklist_preserves_groups_optional_and_inactive_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);d=self.document();v=d['visual_catalog'][0]
            v['saved_score_reference']=dict(cache_need_id='old-car')
            write(p/'media/jev/script-first/beats.json',d)
            write(p/'media/jev/sources.json',{'group-wick1':[],'group-gta5':[],'old-car':[],'unused-control':[]})
            checklist=p/'production/media-checklist.md';checklist.parent.mkdir()
            checklist.write_text('## group-wick1: Film\nhttps://youtu.be/AbCdEf12345\n## group-gta5: Game\nhttps://youtu.be/ZyXwVu98765\n## old-car: Specific\nhttps://youtu.be/QwErTy12345\n## unused-control: Saved\nhttps://youtu.be/MnBvCx98765\n')
            qs=questions(d);source=checklist_sources(p,qs);qid=next(iter(qs))
            self.assertEqual(source['groups']['gta5'],['https://youtu.be/ZyXwVu98765'])
            self.assertEqual(source['optional'][qid],['https://youtu.be/QwErTy12345'])
            self.assertEqual(source['archived']['unused-control'],['https://youtu.be/MnBvCx98765'])
            rendered=render_checklist(d,qs,source,[dict(video_id='tJbzMqJGH4k',reason='Age-gated',action='Replace; no bypass')])
            self.assertLess(rendered.index('Age-gated'),rendered.index('## group-wick1'))
            checklist.write_text(rendered,encoding='utf8');self.assertEqual(checklist_sources(p,qs),source)

    def test_general_pool_uses_full_group_video_not_positive_need_spans(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);vid='AbCdEf12345';path=p/'proxy.mp4';path.write_bytes(b'proxy')
            videos={vid:dict(id=vid,status='ready',path=str(path),crop=None,probe=dict(duration=100))}
            cache=p/'cache';write(cache/'jev-index'/(vid+'.black.json'),dict(ranges=[[10,11]]))
            write(p/'media/jev/script-first/text-scans'/(vid+'.json'),dict(status='complete',source_size=5,crop=None,ranges=[[20,22]]))
            with patch('script_first.pool.cache_dir',return_value=cache):
                result=general_pools(p,dict(groups={'wick1':['https://youtu.be/'+vid],'wick2':[]}),videos,set())
            self.assertIsNone(result[0]['query']);self.assertEqual(result[0]['videos'][0]['usable_ranges'],[[0,10],[11,20],[22,100]])
            self.assertEqual(result[1]['videos'],[])
            used={};last={};a=choose_general(result[0],4,used,last,0);b=choose_general(result[0],4,used,last,5)
            self.assertTrue(a['end']<=b['start'] or b['end']<=a['start'])
            result[0]['status']='pending'
            with self.assertRaisesRegex(ValueError,'scans'):choose_general(result[0],4,used,last,10)

    def test_local_text_screen_filter_ignores_hud_and_live_footage(self):
        card=dict(width=1000,height=500,words=[dict(x=300,y=200,w=300,h=50,chars=12,line=0)])
        self.assertTrue(is_text_screen(card,.95))
        self.assertFalse(is_text_screen(card,.3))
        subtitle=copy.deepcopy(card);subtitle['words'][0]['y']=450
        self.assertFalse(is_text_screen(subtitle,.95))
        hud=copy.deepcopy(card);hud['words'][0].update(x=0,y=0)
        self.assertFalse(is_text_screen(hud,.95))
        self.assertEqual(flat_share(bytes([0,0,0])*100),1)

    def test_old_entry_points_stop_before_reading_or_mutating_project(self):
        from stage3_sources import prepare_project
        from stage3_index import Indexer
        from stage3_resume import run
        from stage4_assign import Assignment
        from stage4_build import build
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);write(p/'media/jev/script-first/approval.json',{})
            for caller in [prepare_project,Indexer,run,Assignment,build]:
                with self.subTest(caller=caller),self.assertRaisesRegex(ValueError,'disabled'):caller(p)
            self.assertEqual(len(list(p.rglob('*.*'))),1)
            status=p/'media/jev/index-status.json';write(status,dict(status='stage3_gate_ready'))
            before=status.read_bytes()
            child=subprocess.run([sys.executable,str(Path(__file__).with_name('stage3_resume.py')),'--project',str(p)],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(child.returncode,0);self.assertIn('disabled',child.stderr)
            self.assertEqual(status.read_bytes(),before)

    @unittest.skipUnless(os.name=='nt' and shutil.which('ffmpeg'),'Windows OCR and ffmpeg integration')
    def test_native_scan_replaces_frames_without_decoder_file_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);video=p/'synthetic.mp4'
            filters="[0:v]drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='CHAPTER THREE':fontcolor=white:fontsize=46:x=(w-tw)/2:y=140[a];[a][1:v]concat=n=2:v=1:a=0[out]"
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=navy:s=640x360:r=2:d=1',
                '-f','lavfi','-i','testsrc2=s=640x360:r=2:d=1','-filter_complex',filters,'-map','[out]','-an','-c:v','libx264',str(video)],
                check=True,capture_output=True)
            with WindowsOcr() as o:
                result=scan_video(dict(id='synthetic',path=str(video),crop=None,probe=dict(duration=2)),[],o,p/'scan.json')
            self.assertEqual(result['frames'],4);self.assertEqual(result['ranges'],[[0,1.25]])


if __name__=='__main__':unittest.main()
