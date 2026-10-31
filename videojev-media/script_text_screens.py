# SPDX-License-Identifier: MIT OR Apache-2.0
"""Query-free text-screen filtering with ffmpeg and local Windows OCR."""
import collections
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from script_first import approve,prepare,read
from stage3_index import union
from stage3_sources import command,pool,save_json

RATE=2
WIDTH,HEIGHT=64,36


class WindowsOcr:
    def __init__(self):
        self.process=subprocess.Popen(['powershell','-NoProfile','-File',str(Path(__file__).with_name('windows_ocr.ps1'))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.lines=queue.Queue()
        def reader():
            for line in self.process.stdout:self.lines.put(line)
            self.lines.put(None)
        self.reader=threading.Thread(target=reader,daemon=True);self.reader.start()
        if self.receive().get('status')!='ready':raise RuntimeError('Windows OCR failed to initialize')

    def receive(self):
        while True:
            line=self.lines.get(timeout=90)
            if line is None:raise RuntimeError('Windows OCR exited: '+self.process.stderr.read()[-1500:])
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('error'):raise RuntimeError(value['error'])
            return value

    def recognize(self,path):
        self.process.stdin.write(json.dumps(dict(path=str(Path(path).resolve())))+'\n');self.process.stdin.flush()
        return self.receive()

    def close(self):
        self.process.stdin.close();self.process.wait(timeout=30);self.reader.join(timeout=3)
        self.process.stdout.close();self.process.stderr.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def flat_share(rgb):
    colors=collections.Counter((rgb[i]//32,rgb[i+1]//32,rgb[i+2]//32) for i in range(0,len(rgb),3))
    return max(colors.values())/(len(rgb)/3)


def is_text_screen(ocr,flatness):
    w,h=ocr['width'],ocr['height']
    central=[r for r in ocr['words'] if .12*w<=r['x']+r['w']/2<=.88*w and .12*h<=r['y']+r['h']/2<=.80*h]
    if not central or flatness<.70:return False
    chars=sum(r['chars'] for r in central)
    lines=len({r['line'] for r in central})
    large=any(r['h']>=.055*h for r in central)
    # shortcut: flat-background OCR catches title/text cards, not every designed end card; review uncertain exclusions before tightening it.
    return chars>=8 and (large or (lines>=3 and chars>=25))


def black_scan(video,cache):
    path=cache/(video['id']+'.black.json')
    if path.exists():return read(path)['ranges']
    c=video.get('crop');filters=(f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']}," if c else '')+'blackdetect=d=0.01:pic_th=0.995:pix_th=0.02'
    r=subprocess.run(['ffmpeg','-hide_banner','-nostats','-threads','2','-i',video['path'],'-vf',filters,'-an','-f','null','-'],
        capture_output=True,text=True,timeout=1800)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    spans=[[float(a),float(b)] for a,b in re.findall(r'black_start:([\d.]+) black_end:([\d.]+)',r.stderr)]
    save_json(path,dict(ranges=spans,settings=filters))
    return spans


def scan_video(video,black,ocr,target):
    started=time.perf_counter();crop=video.get('crop');prefix=f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else ''
    args=['ffmpeg','-v','error','-threads','2','-i',video['path'],'-an','-vf',prefix+f'fps={RATE}:start_time=0:round=up,scale={WIDTH}:{HEIGHT},format=rgb24','-f','rawvideo','-']
    spans=[];evidence=[];frames=0;checks=0
    with tempfile.TemporaryDirectory(prefix='jev-text-') as temporary:
        process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while True:
                pixels=process.stdout.read(WIDTH*HEIGHT*3)
                if not pixels:break
                if len(pixels)!=WIDTH*HEIGHT*3:raise RuntimeError('Incomplete text-screen sample')
                at=frames/RATE;frames+=1
                if any(a<=at<b for a,b in black):continue
                flat=flat_share(pixels)
                if flat<.70:continue
                image=Path(temporary)/'frame.png'
                command(['ffmpeg','-v','error','-y','-ss',str(at),'-i',video['path'],'-an','-frames:v','1','-vf',prefix+'scale=960:-2',str(image)],60)
                result=ocr.recognize(image);checks+=1
                if is_text_screen(result,flat):
                    spans.append([max(0,at-.25),min(video['probe']['duration'],at+.75)])
                    evidence.append(dict(time=at,flat_share=flat,ocr_geometry=result))
            error=process.stderr.read().decode(errors='replace');code=process.wait(timeout=60)
            if code:raise RuntimeError(error[-2000:])
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=30)
            process.stdout.close();process.stderr.close()
    result=dict(status='complete',video_id=video['id'],source_size=Path(video['path']).stat().st_size,crop=crop,
        fps=RATE,method='Flat-background prefilter + central Windows OCR; ordinary HUD/subtitles ignored',
        boundary_uncertainty_seconds=.5,ranges=union(spans),evidence=evidence,frames=frames,ocr_frames=checks,seconds=time.perf_counter()-started)
    save_json(target,result)
    return result


def scan_pools(project):
    import msvcrt
    approve(project)
    with (project/'media/jev/script-first/quality.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('A general-pool quality scan is already running') from exc
        try:_scan_pools(project)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def _scan_pools(project):
    approve(project)
    folder=project/'media/jev/script-first';pools=read(folder/'general-pools.json')
    ids={v['video_id'] for p in pools for v in p['videos'] if v['status']!='not_downloaded'}
    videos={v['id']:v for v in read(project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
    (folder/'text-scans').mkdir(exist_ok=True)
    state=dict(status='running',pid=os.getpid(),started=time.time(),videos=len(ids),completed=[])
    save_json(folder/'quality-run.json',state);prepare(project)
    try:
        with WindowsOcr() as ocr:
            for vid in sorted(ids):
                if (folder/'stop').exists():raise RuntimeError('Creator requested stop; completed scans are saved')
                target=folder/'text-scans'/(vid+'.json')
                if not target.exists():
                    black=black_scan(videos[vid],pool.cache_dir(project)/'jev-index')
                    result=scan_video(videos[vid],black,ocr,target)
                    print(json.dumps(dict(video=vid,seconds=result['seconds'],excluded_text_seconds=sum(b-a for a,b in result['ranges']))),flush=True)
                state['completed'].append(vid);save_json(folder/'quality-run.json',state)
        state['status']='complete'
    except Exception as exc:
        state.update(status='failed',error=str(exc));raise
    finally:
        state['elapsed_seconds']=time.time()-state['started'];save_json(folder/'quality-run.json',state);prepare(project)
