# SPDX-License-Identifier: MIT OR Apache-2.0
"""Five-second references for the actual treatment and motion renderer."""
import html
import json
import subprocess
from pathlib import Path

FAMILIES = {
    'progressive': ('Progressive card', 'Points appear one at a time in a vertical list and stay on screen together.'),
    'comparison': ('Comparison card', 'Two statements sit side by side. The second appears later and takes emphasis.'),
    'source-card': ('Source card', 'A supplied statement appears with its source or context line underneath. The source line still needs to be correct.'),
}
MOTIONS = {
    'slide-fade': ('slide + fade', 'Text moves upward while fading in, then settles.'),
    'pop': ('pop', 'Text grows slightly into place with a small spring settle.'),
    'fade': ('fade', 'Text quietly fades in and out without moving or changing size.'),
    'impact': ('impact', 'Text pops into place with a brief, small wobble. This is visual emphasis; it does not add a sound.'),
}


def catalog(folder):
    entries={kind+'-'+motion:dict(name=name+' · '+label,description=description+' '+explanation)
             for kind,(name,description) in FAMILIES.items() for motion,(label,explanation) in MOTIONS.items()}
    entries.update(keep=dict(name='Keep current edit',description='Retain the existing picture, cards, captions and sound.'),
        **{'none-of-these':dict(name='None of these — send for review',description='The supplied options do not work or there is not enough information. Ask for review; the current edit stays in place.')})
    manifest=folder/'style-examples/manifest.json'
    if manifest.exists():
        saved=json.loads(manifest.read_text(encoding='utf8'))
        for key,record in saved['examples'].items():
            if key not in entries: continue
            for field in ['file','poster']:
                name=record.get(field)
                if name and Path(name).name==name and not any(c in name for c in '/\\:'):
                    entries[key][field]='style-examples/'+name
    return entries


def example_props(kind,motion):
    content={
        'progressive':dict(title='Points build up',labels=['FIRST SUPPLIED POINT','SECOND SUPPLIED POINT','THIRD SUPPLIED POINT'],reveals=[15,53,90]),
        'comparison':dict(title='Two statements',labels=['FIGHT WON','STILL WANTED'],reveals=[15,60]),
        'source-card':dict(title='Scene reference',labels=['7 ROUNDS'],sourceLabel='CHAPTER 2: BOWERY GIFT',reveals=[15]),
    }
    return dict(width=1920,height=1080,fps=30,duration=150,background='background.mp4',kind=kind,motion=motion,**content[kind])


def generate(folder):
    from editing_recipe import RENDERER,digest,file_hash,inspect_media,save_json
    folder=folder.resolve()
    if not (folder/'editing-recipe.json').is_file() or any((p/'.git').exists() for p in [folder,*folder.parents]):
        raise ValueError('Use a prepared review folder outside Git')
    work=folder/'style-examples';work.mkdir(exist_ok=True);assets=work/'assets';assets.mkdir(exist_ok=True)
    previous=json.loads((work/'manifest.json').read_text(encoding='utf8')) if (work/'manifest.json').exists() else {}
    background=assets/'background.mp4'
    if not background.exists():
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=0x263043:s=1920x1080:r=30',
            '-frames:v','150','-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',str(background)],check=True,timeout=120)
    code={p.name:file_hash(p) for p in (RENDERER/'src').glob('*.ts*')}
    code['package-lock.json']=file_hash(RENDERER/'package-lock.json')
    records={}
    for kind in FAMILIES:
        for motion in MOTIONS:
            key=kind+'-'+motion;props=example_props(kind,motion)
            identity=digest(dict(props=props,code=code,background=file_hash(background),render=dict(scale=.5,crf=23)))
            name=key+'-'+identity[:12];output=work/(name+'.mp4');poster=work/(name+'.jpg');receipt=work/(name+'.json')
            if receipt.exists():
                record=json.loads(receipt.read_text(encoding='utf8'))
                if file_hash(output)!=record['sha256'] or file_hash(poster)!=record['poster_sha256']: raise ValueError('Style reference changed: '+key)
            else:
                props_file=work/(name+'.props.json');save_json(props_file,props)
                command=['node',str(RENDERER/'node_modules/@remotion/cli/remotion-cli.js'),'render',str(RENDERER/'src/recipe-index.tsx'),
                    'RecipeInsert',str(output),'--props',str(props_file),'--public-dir',str(assets),'--codec','h264','--crf','23','--scale','0.5','--concurrency','2','--log','error']
                with (work/(name+'.log')).open('w',encoding='utf8') as log:
                    subprocess.run(command,cwd=RENDERER,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
                info=inspect_media(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
                if int(video['nb_frames'])!=150 or (video['width'],video['height'])!=(960,540) or abs(float(info['format']['duration'])-5)>.04 or any(s['codec_type']=='audio' for s in info['streams']):
                    raise ValueError('Style reference must contain exactly five silent seconds at 540p')
                subprocess.run(['ffmpeg','-v','error','-y','-ss','2.5','-i',str(output),'-frames:v','1',str(poster)],check=True,timeout=60)
                record=dict(file=output.name,poster=poster.name,sha256=file_hash(output),poster_sha256=file_hash(poster),seconds=5,frames=150,width=960,height=540)
                save_json(receipt,record)
            records[key]=record;print('Verified five-second example: '+key,flush=True)
    current=folder/'star4-preview-540p.mp4'
    if current.exists():
        name='keep-'+file_hash(current)[:12];output=work/(name+'.mp4');poster=work/(name+'.jpg')
        if output.exists():
            record=previous.get('examples',{}).get('keep',{})
            if record.get('file')!=output.name or file_hash(output)!=record.get('sha256') or not poster.exists() or file_hash(poster)!=record.get('poster_sha256'):
                raise ValueError('Current-edit reference is unverified or changed')
        else:
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(current),'-frames:v','150','-an','-c:v','libx264','-preset','veryfast','-crf','23',str(output)],check=True,timeout=120)
            subprocess.run(['ffmpeg','-v','error','-y','-ss','2.5','-i',str(output),'-frames:v','1',str(poster)],check=True,timeout=60)
            info=inspect_media(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
            if int(video['nb_frames'])!=150 or abs(float(info['format']['duration'])-5)>.04:
                raise ValueError('Current-edit reference must contain exactly five seconds')
            record=dict(file=output.name,poster=poster.name,sha256=file_hash(output),poster_sha256=file_hash(poster),seconds=5,frames=150)
        records['keep']=record;records['none-of-these']=record
    save_json(work/'manifest.json',dict(seconds=5,model_calls=0,examples=records))
    write_gallery(folder)
    return records


def write_gallery(folder):
    entries=catalog(folder);cards=[]
    for key,e in entries.items():
        if 'file' not in e: continue
        source=html.escape(Path(e['file']).name);poster=html.escape(Path(e['poster']).name)
        cards.append('<article id="'+key+'"><h2>'+html.escape(e['name'])+'</h2><video controls muted loop playsinline preload="none" src="'+source+'" poster="'+poster+'"></video><p>'+html.escape(e['description'])+'</p></article>')
    (folder/'style-examples/index.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Five-second editing examples</title><style>body{font:17px system-ui;background:#171b24;color:#f4f0e8;max-width:1500px;margin:30px auto;padding:0 20px}a{color:#e3bb78}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:22px}article{border:1px solid #555;border-radius:12px;padding:16px;scroll-margin-top:20px}h2{font-size:21px}video{width:100%;background:#080c13}p{line-height:1.5}</style><h1>Five-second editing examples</h1><p>Play a clip to see its layout and motion. All examples are silent. The sample words teach the style; use the actual beat and its evidence when choosing an edit.</p><p><a href="../calibration.html">Back to calibration</a></p><div class="grid">'+''.join(cards)+'</div>',encoding='utf8')


def preview_ui(folder):
    entries=catalog(folder)
    payload=json.dumps(entries,ensure_ascii=True).replace('<','\\u003c')
    return '<style>dialog{box-sizing:border-box;width:min(960px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;border:1px solid #777;border-radius:12px;padding:24px;font:17px system-ui}dialog::backdrop{background:#000a}dialog video{width:100%;max-height:60vh}dialog button{float:right}select,button{font:inherit}button{padding:8px;cursor:pointer}button:disabled{cursor:default}</style><dialog id="style-example" aria-labelledby="style-example-title"><button type="button" onclick="document.getElementById(\'style-example\').close()">Close</button><h2 id="style-example-title"></h2><p id="style-example-description"></p><video id="style-example-video" controls muted loop playsinline preload="none"></video><p>Five-second silent reference. Use the actual beat and evidence to judge the edit.</p><a id="style-example-gallery" target="_blank" rel="noopener">Compare all examples</a></dialog><script type="application/json" id="style-example-data">'+payload+'''</script><script>
function showStyle(value){
  const e=JSON.parse(document.getElementById('style-example-data').textContent)[value];
  if(!e)return;
  document.getElementById('style-example-title').textContent=e.name;
  document.getElementById('style-example-description').textContent=e.description;
  const video=document.getElementById('style-example-video');
  video.hidden=!e.file;
  if(e.file){video.src=e.file;if(e.poster)video.poster=e.poster;video.load();}
  document.getElementById('style-example-gallery').href='style-examples/index.html#'+encodeURIComponent(value);
  const dialog=document.getElementById('style-example');dialog.showModal();
  dialog.onclose=()=>{video.pause();video.removeAttribute('src');video.load();};
  if(e.file)video.play().catch(()=>{});
}
</script>'''


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    generate(parser.parse_args().folder)
