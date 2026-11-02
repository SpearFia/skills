# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stage6_finalize import Finalize,alignment,blocked,crop_filter,cut_master,fetch_ranges,media_info,scaled_sequence,selection


class Stage6Tests(unittest.TestCase):
    def test_hls_probe_uses_nominal_rate_when_average_is_missing(self):
        data=dict(streams=[dict(codec_type='video',avg_frame_rate='0/0',r_frame_rate='24000/1001',width=1920,height=1080,duration='10')],format={})
        with patch('stage6_finalize.command',return_value=json.dumps(data)):
            info=media_info('part.ts')
        self.assertAlmostEqual(info['fps'],24000/1001);self.assertTrue(info['video_only'])

    def test_only_visible_selected_masters_are_download_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            def item(name):return {'kind':{'Media':{'media':{'File':{'path':str(p/name)}},'info':{'video':{'width':854,'height':480}}}}}
            items={'1':item('unused.mp4'),'2':item('chosen.mp4'),'3':item('disabled.mp4'),'4':item('title-sting.mp4')}
            def clip(i,item,a,b,enabled=True):return dict(id=i,item=item,name=str(i),start=a,duration=b-a,enabled=enabled)
            seq=dict(video_tracks=[dict(enabled=True,items=[clip(1,1,0,200)]),dict(enabled=True,items=[clip(2,2,0,100),clip(3,2,100,200),clip(4,3,200,300,False),clip(5,4,200,240)])])
            masters={str((p/name).resolve()).casefold():dict(file=name,video_id=name,start=0,end=10) for name in ['unused.mp4','chosen.mp4','disabled.mp4']}
            with patch('stage6_finalize.footage_tracks',return_value=seq['video_tracks']),patch('stage6_finalize.master_map',return_value=masters):
                result=selection(p,dict(project=dict(items=items)),seq)
            self.assertEqual([a['master']['file'] for a in result['assets']],['chosen.mp4'])
            self.assertEqual(result['assets'][0]['clips'],[2,3]);self.assertEqual(result['assets'][0]['items'],[2])
            self.assertEqual(len(result['generated']),1);self.assertEqual(result['unmapped'],[])

    def test_crop_scales_source_coordinates_and_does_not_upscale_resolution(self):
        master=dict(crop=dict(w=854,h=356,x=0,y=62),proxy_size=[854,480])
        vf,crop=crop_filter(master,dict(width=1920,height=1080))
        self.assertEqual(crop,dict(w=1920,h=800,x=0,y=140));self.assertNotIn('scale=',vf)
        self.assertEqual(crop_filter(dict(crop=None),dict(width=1280,height=720)),('setsar=1',None))

    def test_relink_scales_only_source_anchor_and_preserves_retiming_and_zoom_keys(self):
        clip=dict(id=5,item=7,scale_to_frame=True,start=123,duration=456,source_in=78,speed=.5,reverse=False,effects=[dict(effect='motion',params=dict(
            anchor=dict(value=dict(Vec2=dict(x=576.,y=240.))),scale=dict(value=dict(Float=100.),keyframes=[dict(time=100,value=dict(Float=100.)),dict(time=200,value=dict(Float=120.))])))])
        seq=dict(video_tracks=[dict(items=[clip])],audio_tracks=[dict(items=['voice'])],caption_tracks=[dict(text='unchanged')],markers=[1,2]);before=copy.deepcopy(seq)
        items={'7':{'kind':{'Media':{'info':{'video':{'width':1152,'height':480}}}}}}
        expected,anchors=scaled_sequence(seq,items,{7:dict(info=dict(width=1920,height=800))})
        self.assertEqual(anchors,{5:[960.,400.]});self.assertEqual(seq,before)
        expected['video_tracks'][0]['items'][0]['effects'][0]['params']['anchor']['value']['Vec2']=dict(x=576.,y=240.)
        self.assertEqual(expected,before)
        clip['scale_to_frame']=False
        with self.assertRaisesRegex(ValueError,'Scale to Frame'):scaled_sequence(seq,items,{7:dict(info=dict(width=1920,height=800))})

    def test_segment_fetch_merging_is_bounded(self):
        assets=[dict(master=dict(start=a,end=b)) for a,b in [(0,10),(18,30),(130,170),(175,220),(225,340)]]
        spans=fetch_ranges(assets)
        self.assertEqual(spans,[dict(start=0,end=30),dict(start=130,end=220),dict(start=225,end=340)])
        self.assertTrue(all(s['end']-s['start']<=180 for s in spans))

    def test_cached_build_verifies_native_changes_and_returns_saved_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);target=folder/'final.fcproj';target.write_text('saved')
            (folder/'build.json').write_text(json.dumps(dict(review=str(target))))
            f=Finalize.__new__(Finalize);f.folder=folder;f.project=folder;f.plan=dict(assets=[]);f.results={};f.data=dict(project=dict(items={}))
            f.sequence=dict(video_tracks=[dict(items=[dict(id=7,item=99,effects=[dict(effect='graphic_text',params=dict(
                position=dict(value=dict(Vec2=dict(x=1920.,y=1994.4000028967857)))))])])])
            saved=copy.deepcopy(f.sequence)
            saved['video_tracks'][0]['items'][0]['effects'][0]['params']['position']['value']['Vec2']['y']=1994.4000028967855
            with patch('stage6_finalize.load_review',return_value=(dict(project=dict(items={})),saved)),patch('stage6_finalize.FilmCraft') as api:
                path,expected,upgraded=f.build()
                self.assertEqual((path,expected,upgraded),(str(target),saved,{}));api.assert_not_called()
                saved['video_tracks'][0]['items'][0]['duration']=301
                with self.assertRaisesRegex(AssertionError,'Native sequence changed'):f.build()

    def test_access_restriction_does_not_trigger_download_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Finalize.__new__(Finalize);f.cache=Path(tmp);f.status=lambda phase:None
            with patch('stage6_finalize.pool.stream_clips',side_effect=SystemExit('Sign in to confirm your age')),patch('stage6_finalize.pool.fetch') as full:
                with self.assertRaisesRegex(RuntimeError,'Blocked source'):f.download(dict(id='v',url='test',probe=dict(duration=100)),[dict(master=dict(start=0,end=5))])
                full.assert_not_called()
        self.assertTrue(blocked('HTTP Error 429'))
        self.assertFalse(blocked('Requested format is not available'))

    def test_unavailable_hls_falls_back_once_and_reuses_saved_source_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Finalize.__new__(Finalize);f.cache=Path(tmp);f.status=lambda phase:None;source=Path(tmp)/'full.mp4';source.write_bytes(b'source')
            video=dict(id='v',url='test',probe=dict(duration=100));assets=[dict(master=dict(start=10,end=20))]
            with patch('stage6_finalize.pool.stream_clips',side_effect=ValueError('No HLS stream')) as stream,patch('stage6_finalize.pool.fetch',return_value=(source,'v','test',{})) as full:
                first=f.download(video,assets);second=f.download(video,assets)
                self.assertEqual(first,second);self.assertEqual(first[0]['kind'],'full');self.assertEqual(first[0]['offset'],0)
                self.assertEqual(f.download(video,[dict(master=dict(start=12,end=16))]),first)
                self.assertEqual(stream.call_count,1);self.assertEqual(full.call_count,1)

    def test_hls_starting_at_zero_remains_a_fragment_and_never_downloads_the_full_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Finalize.__new__(Finalize);f.cache=Path(tmp);f.status=lambda phase:None;part=Path(tmp)/'part.ts';part.write_bytes(b'hls')
            with patch('stage6_finalize.pool.stream_clips',return_value=[(part,0)]),patch('stage6_finalize.media_info',return_value=dict(width=1920,height=1080)),patch('stage6_finalize.pool.fetch') as full:
                parts=f.download(dict(id='v',url='test',probe=dict(duration=100)),[dict(master=dict(start=0,end=5))])
                self.assertEqual(parts[0]['kind'],'hls');full.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg integration')
    def test_alignment_accepts_resolution_change_and_rejects_source_time_shift(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);old=p/'proxy.mp4';new=p/'larger.mp4';wrong=p/'shifted.mp4'
            filters="nullsrc=s=160x90:r=24:d=3,geq=r='mod(N*55,256)':g='mod(N*97,256)':b='mod(N*149,256)'"
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',filters,'-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-threads','2',str(old)],check=True,capture_output=True,timeout=45)
            for target,seek in [(new,0),(wrong,.5)]:
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(seek),'-i',str(old),'-vf','scale=640:360','-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-threads','2',str(target)],check=True,capture_output=True,timeout=45)
            self.assertTrue(all(r['matched'] for r in alignment(old,new,media_info(old),media_info(new))))
            with self.assertRaisesRegex(ValueError,'source time/crop'):alignment(old,wrong,media_info(old),media_info(wrong))
            short=p/'B-roll/short.mp4';short.parent.mkdir()
            subprocess.run(['ffmpeg','-v','error','-y','-ss','0.75','-i',str(old),'-t','1.25','-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-threads','2',str(short)],check=True,capture_output=True,timeout=45)
            cache=p/'cache';cache.mkdir();asset=dict(master=dict(file='B-roll/short.mp4',video_id='v',start=.75,end=2.,crop=None,proxy_size=[160,90]))
            result=cut_master(p,asset,wrong,.5,media_info(wrong),cache,fragment=True)
            self.assertEqual((result['source_start'],result['source_end'],result['source_offset']),(.75,2.,.5))
            self.assertEqual(result['info']['width'],640);self.assertFalse(result['source_1080p']);self.assertTrue(result['info']['video_only'])


if __name__=='__main__':unittest.main()
