# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small bounded stdio client for the installed FilmCraft CLI."""
import json
import queue
import subprocess
import threading


class FilmCraft:
    def __init__(self):
        self.process=subprocess.Popen([r'C:\Program Files\FilmCraft\filmcraft-cli.exe','mcp'],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        self.lines=queue.Queue();self.next_id=1
        def read():
            for line in self.process.stdout:self.lines.put(line)
            self.lines.put(None)
        threading.Thread(target=read,daemon=True).start()
        self.request('initialize',dict(protocolVersion='2025-06-18',capabilities={},clientInfo=dict(name='videojev-stage4',version='1')))
        self.send(dict(jsonrpc='2.0',method='notifications/initialized'))

    def send(self,value):
        self.process.stdin.write(json.dumps(value)+'\n');self.process.stdin.flush()

    def request(self,method,params):
        key=self.next_id;self.next_id+=1
        self.send(dict(jsonrpc='2.0',id=key,method=method,params=params))
        while True:
            line=self.lines.get(timeout=180)
            if line is None:raise RuntimeError('FilmCraft exited')
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('id')!=key:continue
            if 'error' in value:raise RuntimeError(str(value['error']))
            return value['result']

    def tool(self,name,args):
        result=self.request('tools/call',dict(name=name,arguments=args))
        if result.get('isError'):raise RuntimeError(str(result.get('content'))[:1500])
        if result.get('structuredContent'):return result['structuredContent']
        text=next((c['text'] for c in result.get('content',[]) if c.get('type')=='text'),'{}')
        return json.loads(text)

    def command(self,command_id,**params):
        return self.tool('command_run',dict(id=command_id,params=params))

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=30)

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
