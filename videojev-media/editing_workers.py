# SPDX-License-Identifier: MIT OR Apache-2.0
"""Separate VideoJev and Clef phases; stop only workers owned by this invocation."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from stage3_index import Indexer,wsl_path
from script_first import read
from stage3_sources import save_json


def check_idle():
    from stage3_sources import command
    from demo import check_ready
    try:
        with urllib.request.urlopen('http://127.0.0.1:8188/queue',timeout=3) as r: queue=json.load(r)
    except OSError:
        active=command(['powershell','-NoProfile','-Command',"Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|comfy' -and $_.CommandLine -match 'ComfyUI|main.py' } | Select-Object -ExpandProperty ProcessId"],30).strip()
        if active: raise RuntimeError('ComfyUI queue cannot be verified')
        queue=dict(queue_running=[],queue_pending=[])
    free=int(command(['nvidia-smi','--id=0','--query-gpu=memory.free','--format=csv,noheader,nounits'],30).strip())
    check_ready(queue,free,10000)


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8008/health',timeout=3) as r: return json.load(r)
    except OSError: return None


class ClefSession:
    def __init__(self,folder,owner):
        self.folder=folder;self.owner=owner;self.worker=None;self.pid_file=folder/(owner+'.pid')

    def __enter__(self):
        from editing_recipe import MODEL,REVISION,RENDERER
        current=health()
        if current:
            if current.get('model')!=MODEL or current.get('revision')!=REVISION: raise ValueError('Another service owns the Clef port')
            return current
        check_idle()
        script=wsl_path(RENDERER/'run-clef-wsl.sh')
        self.pid_file.unlink(missing_ok=True)
        self.log=(self.folder/'clef-worker.log').open('a',encoding='utf8')
        self.worker=subprocess.Popen(['wsl','-d','Ubuntu','--','env','SPEARFIA_CLEF_OWNER='+self.owner,'SPEARFIA_CLEF_PID_FILE='+wsl_path(self.pid_file),'sh',script],
            stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(600):
            current=health()
            if current and current.get('owner')==self.owner:
                save_json(self.folder/'clef-runtime.json',current);return current
            if self.worker.poll() is not None:
                self.log.close();raise RuntimeError('Clef load failed; see clef-worker.log')
            time.sleep(1)
        self.__exit__();raise TimeoutError('Clef did not become ready')

    def __exit__(self,*args):
        current=health()
        if self.worker:
            if self.worker.poll() is None:
                pid=current['pid'] if current and current.get('owner')==self.owner else int(self.pid_file.read_text())
                if pid<=1:raise ValueError('Invalid owned worker PID')
                subprocess.run(['wsl','-d','Ubuntu','--','kill','-TERM',str(pid)],check=True,timeout=30)
            self.worker.wait(timeout=60);self.log.close()


class EvidenceWorker(Indexer):
    def __init__(self,folder):
        self.cache=folder;self.tasks=folder/'tasks';self.tasks.mkdir(parents=True,exist_ok=True)
        self.config=read(Path(__file__).with_name('config.json'));self.state={};self.worker=None;self.timings=[]


def gather(folder,recipe):
    from editing_recipe import digest,file_hash
    # Incomplete editorial intent cannot be repaired by another visual-model call.
    pending={}
    for p in recipe['windows']:
        if not p['candidates'] or 'missing-explicit-reveal-anchors' in p['flags'] or p['evidence_adequate']: continue
        for source in p['footage']:
            if source['flags']: continue
            binding=next(b for b in recipe['media_bindings'] if b['source_id']==source['id'])
            master=source['master'];a=source['source_interval']['start']/254016000000-master['start'];b=source['source_interval']['end']/254016000000-master['start']
            for plan in p.get('evidence_questions',[]):
                query=plan.get('query')
                if not query: continue
                identity=dict(path=binding['path'],sha256=binding['sha256'],a=a,b=b,query=query,crop=source['crop'])
                pending[digest(identity)]=identity
    saved={};calls=0
    if pending and health(): raise RuntimeError('Release the other Clef service before the VideoJev phase')
    worker=EvidenceWorker(folder/'video-evidence') if pending else None
    try:
        for key,job in pending.items():
            dest=worker.cache/(key+'.json')
            if dest.exists(): saved[key]=read(dest);continue
            if file_hash(job['path'])!=job['sha256']: raise ValueError('Evidence asset changed')
            if not worker.worker: worker.start_worker()
            question=dict(id=key,task='choice',query='Which statement matches the visible picture?',options=[job['query'],'The described content is absent.','The picture is unclear.','None of these.'])
            _,result=worker.predict(dict(id=key,path=job['path']),job['a'],job['b'],2,[question])
            calls+=1;saved[key]=dict(input=job,result=result,creator_review='pending');save_json(dest,saved[key])
    finally:
        if worker and worker.worker:
            (worker.tasks/'stop').touch();worker.worker.wait(timeout=60)
    result=dict(model_calls=calls,observations=saved,policy='General footage remains query-free; incomplete intent is flagged for review')
    save_json(folder/'video-evidence.json',result);return result
