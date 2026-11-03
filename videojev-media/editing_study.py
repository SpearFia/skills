# SPDX-License-Identifier: MIT OR Apache-2.0
"""Editing studies on complete videos: independent opportunity and treatment judgments."""
import argparse
from contextlib import nullcontext
import html
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import uuid

from editing_policy import require_short_study
from editing_recipe import MODEL,REVISION,assess,digest,exclusive,file_hash,inspect_media,read,save_json
from editing_workers import ClefSession

OPPORTUNITY = {
    'graphic-helpful':'An information graphic has a useful explanatory role in this beat, including when a useful graphic is already present.',
    'footage-sufficient':'The supplied footage or current presentation communicates this beat well without an explanatory graphic.',
    'uncertain':'The narration or current-presentation information is insufficient to judge the role of a graphic.',
}
OPPORTUNITY_CRITERIA = ('Judge whether a graphic has a useful explanatory role in the supplied beat. Consider meaningful contrasts, counts, sequences and source references. '
    'Do not decide whether to replace the current graphic, and do not require ready-made wording or a treatment menu to recognize a useful role. '
    'Prefer footage-sufficient when a graphic would add clutter or merely repeat a clear action. Choose uncertain when context is inadequate. Do not write labels or facts.')
TREATMENT_CRITERIA = ('Choose among the complete supplied pop treatments. Use a comparison for two distinct statements on the same basis, a progressive card for points that build in order, '
    'or a source card for a supplied statement and its correct provenance. Preserve qualifiers and reading time. '
    'Choose keep when the current presentation serves the beat better. Choose none-of-these when a graphic may help but no supplied treatment is supported. Do not invent wording or sources.')
SCHEMA_REPO = Path(__file__).resolve().parents[2]/'spearfia-spec-editing'


def validate_document(path):
    if path.stat().st_size>262144:raise ValueError('Study manifest is too large')
    lib=SCHEMA_REPO.parent/'spearfia-spec/scripts/lib.mjs'
    script='import {validator,report} from '+json.dumps(lib.as_uri())+'; if(!report(validator("editing-study",process.argv[1]),process.argv[2])) process.exit(1);'
    result=subprocess.run(['node','--input-type=module','-e',script,str(SCHEMA_REPO/'schemas'),str(path)],capture_output=True,text=True,timeout=30)
    if result.returncode:raise ValueError('Invalid editing-study contract: '+(result.stdout+result.stderr)[-3000:])


def validate_study(study,path):
    media=Path(study['media']['path'])
    if not media.is_absolute():media=path.parent/media
    media=media.resolve()
    require_short_study(study['duration_ms']/1000,media,study.get('source_project',''))
    if not media.is_file() or file_hash(media)!=study['media']['sha256']:raise ValueError('Short-study media is missing or changed')
    info=inspect_media(media)
    if not any(s['codec_type']=='video' for s in info['streams']):raise ValueError('Study needs a real short video')
    duration=float(info['format']['duration'])
    require_short_study(duration,media,study.get('source_project',''))
    if abs(round(duration*1000)-study['duration_ms'])>100:raise ValueError('Declared study duration does not match the complete source video')
    seen=set();last=0
    for beat in study['beats']:
        if beat['id'] in seen or beat['start_ms']<last or not beat['start_ms']<beat['end_ms']<=study['duration_ms']:raise ValueError('Invalid or overlapping study beats')
        seen.add(beat['id']);last=beat['end_ms'];ids={'keep','none-of-these'}
        for c in beat['candidates']:
            if c['id'] in ids or c['motion']!='pop':raise ValueError('Candidate IDs must be unique and all motion must be pop')
            ids.add(c['id'])
            if len(c['labels'])!=len(c['reveal_ms']) or c['reveal_ms']!=sorted(c['reveal_ms']):raise ValueError('Candidate labels need ordered supplied reveal anchors')
            if any(not beat['start_ms']<=t<=beat['end_ms']-600 for t in c['reveal_ms']):raise ValueError('Candidate reveal lies outside its beat or has no reading time')
            if c['kind']=='comparison' and len(c['labels'])!=2:raise ValueError('A comparison needs two supplied statements')
            if c['kind']=='progressive' and len(c['labels'])<2:raise ValueError('A progressive card needs at least two supplied points')
            if c['kind']=='source-card' and not c.get('source_label','').strip():raise ValueError('A source card needs supplied provenance')
    return media


def packets(study):
    result=[]
    for i,beat in enumerate(study['beats']):
        common=dict(media_sha256=study['media']['sha256'],interval=dict(start_ms=beat['start_ms'],end_ms=beat['end_ms']),
            narration=beat['narration'],current_presentation=beat['current_presentation'],visual_intent=beat.get('visual_intent',''),
            evidence=beat.get('evidence',[]),neighbors=[b['narration'] for j,b in enumerate(study['beats']) if abs(i-j)==1])
        stages=[('opportunity',common,OPPORTUNITY_CRITERIA,OPPORTUNITY)]
        if beat['candidates']:
            choices={'keep':'Keep the current presentation',**{c['id']:json.dumps(c,ensure_ascii=False) for c in beat['candidates']},'none-of-these':'No supplied treatment fits safely; review is needed'}
            stages.append(('treatment',dict(common,candidates=beat['candidates'],motion='pop'),TREATMENT_CRITERIA,choices))
        for stage,state,instructions,choices in stages:
            p=dict(id=beat['id'],stage=stage,state=state,criteria=instructions,options=choices,model_revision=REVISION)
            p['context_sha256']=digest(p);result.append(p)
    return result


def predict(packet):
    stage=packet['stage']
    request=dict(model=MODEL,state=packet['state'],questions={stage:dict(type='choice',instructions=packet['criteria'],criteria=packet['options'])})
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8008/v1/systemone',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'}),timeout=180) as r:
        response=json.load(r)
    assessment=assess(dict(options=list(packet['options']),flags=['recommendations-only'],evidence_adequate=False,candidates=packet['state'].get('candidates',[])),response,stage)
    return dict(context_sha256=packet['context_sha256'],stage=stage,status='complete',response=response,assessment=assessment)


def evaluate(study,report,labels):
    if labels.get('study_sha256')!=digest(study):raise ValueError('Creator labels refer to a different short study')
    beats={b['id']:b for b in study['beats']};seen=set();scores={stage:dict(count=0,matches=0) for stage in ['opportunity','treatment']}
    for row in labels['labels']:
        if row['id'] in seen or row['id'] not in beats:raise ValueError('Unknown or duplicate study label')
        seen.add(row['id']);r=report['decisions'][row['id']]
        for stage in scores:
            expected=row.get(stage)
            if expected is None:continue
            prediction=r.get(stage)
            valid=set(OPPORTUNITY) if stage=='opportunity' else {'keep','none-of-these',*[c['id'] for c in beats[row['id']]['candidates']]}
            if expected not in valid:raise ValueError('Unknown stage-specific creator choice')
            if not prediction or prediction['status']=='not-asked':continue
            if row.get(stage+'_context_sha256')!=prediction['context_sha256']:raise ValueError('Stale stage-specific creator label')
            if prediction['status']!='complete':continue
            scores[stage]['count']+=1;scores[stage]['matches']+=expected==prediction['assessment']['choice']
            if stage=='treatment':
                assessment=prediction['assessment']
                group=lambda choice:'graphic' if choice not in {'keep','none-of-these'} else 'no graphic' if choice=='keep' else choice
                scores[stage]['grouped_matches']=scores[stage].get('grouped_matches',0)+(group(expected)==group(assessment['grouped_choice']))
    for stage,score in scores.items():
        score['agreement']=score['matches']/score['count'] if score['count'] else None
        score['exact_agreement']=score['agreement']
        if stage=='treatment':score['grouped_agreement']=score.get('grouped_matches',0)/score['count'] if score['count'] else None
    return dict(split=study['split'],stages=scores,deployment_enabled=False,scope='Descriptive component results only; no deployment gate is enabled')


def run_study(path,out,labels_path=None):
    path=path.resolve();out=out.resolve();validate_document(path);study=read(path);media=validate_study(study,path)
    if any((p/'.git').exists() for p in [out,*out.parents]):raise ValueError('Study output must be outside Git')
    if study.get('source_project'):
        project=Path(study['source_project'])
        if not project.is_absolute():project=path.parent/project
        if out.is_relative_to(project.resolve()):raise ValueError('Study output must be separate from the source project')
    for p in [media.parent,*media.parents]:
        if (p/'project.json').exists() and out.is_relative_to(p):raise ValueError('Study output must be separate from the source project')
    if out.exists() and not (out/'study.json').exists() and any(out.iterdir()):
        raise ValueError('Use a fresh output; existing reviews must be preserved')
    out.mkdir(parents=True,exist_ok=True)
    with exclusive(out):
        source=out/'study.json';identity=digest(study)
        if source.exists() and digest(read(source))!=identity:raise ValueError('This folder contains another frozen study; use a fresh output')
        if not source.exists():shutil.copy2(path,source)
        work=packets(study);cache=out/'decisions';cache.mkdir(exist_ok=True)
        decisions={b['id']:dict(treatment=dict(status='not-asked',reason='No complete supplied treatment; opportunity can still be judged')) for b in study['beats']}
        missing=[]
        for p in work:
            saved=cache/(p['context_sha256']+'.json')
            if not saved.exists():missing.append(p);continue
            record=read(saved)
            if record.get('context_sha256')!=p['context_sha256'] or record.get('stage')!=p['stage'] or record.get('status')!='complete':raise ValueError('Invalid short-study decision cache')
            record['assessment']=assess(dict(options=list(p['options']),flags=['recommendations-only'],evidence_adequate=False,candidates=p['state'].get('candidates',[])),record.get('response'),p['stage'])
            decisions[p['id']][p['stage']]=record
        calls={stage:0 for stage in ['opportunity','treatment']}
        try:
            with ClefSession(out,uuid.uuid4().hex) if missing else nullcontext():
                for p in missing:
                    saved=cache/(p['context_sha256']+'.json')
                    try:
                        calls[p['stage']]+=1;record=predict(p);save_json(saved,record)
                        decisions[p['id']][p['stage']]=record
                    except (OSError,RuntimeError,ValueError) as exc:
                        decisions[p['id']][p['stage']]=dict(status='failed',context_sha256=p['context_sha256'],error=str(exc))
        except (OSError,RuntimeError,TimeoutError) as exc:
            for p in missing:
                if p['stage'] not in decisions[p['id']] or decisions[p['id']][p['stage']]['status']=='not-asked':
                    decisions[p['id']][p['stage']]=dict(status='failed',context_sha256=p['context_sha256'],error=str(exc))
        report=dict(study_sha256=identity,mode='recommendations-only',motion='pop',deployment_enabled=False,model_requests=calls,decisions=decisions)
        label_copy=out/'creator-labels.json'
        label_source=labels_path or (label_copy if label_copy.exists() else None)
        if label_source:
            report['evaluation']=evaluate(study,report,read(label_source))
            if label_copy.exists() and file_hash(label_source)!=file_hash(label_copy):raise ValueError('Earlier creator labels must be preserved; use a fresh study for another review')
            if not label_copy.exists():shutil.copy2(label_source,label_copy)
            report['creator_labels_sha256']=file_hash(label_copy)
        save_json(out/'study-report.json',report)
        save_json(out/'decision-contexts.json',work)
        write_report(out,study,report,media)
        if file_hash(media)!=study['media']['sha256']:raise ValueError('Study media changed during judgment')
        return report


def write_report(folder,study,report,media):
    from calibration_examples import FAMILIES,preview_ui
    rows=[];label_rows=[]
    for i,b in enumerate(study['beats']):
        r=report['decisions'][b['id']]
        def describe(stage):
            record=r[stage]
            if record['status']=='complete':
                a=record['assessment']
                return a['choice']+('; grouped: '+a['grouped_choice'] if stage=='treatment' else '')
            return record.get('reason',record.get('error','Model judgment unavailable'))
        rows.append('<tr><td>'+html.escape(b['id'])+'</td><td>'+html.escape(b['narration'])+'</td><td>'+html.escape(describe('opportunity'))+'</td><td>'+html.escape(describe('treatment'))+'</td></tr>')
        op='<option value="">Choose…</option>'+''.join('<option value="'+k+'">'+html.escape(v)+'</option>' for k,v in OPPORTUNITY.items())
        options=[('keep','Keep current presentation'),*[(c['id'],FAMILIES[c['kind']][0]+' · pop: '+' / '.join(c['labels'])) for c in b['candidates']],('none-of-these','None of these / needs review')]
        tx='<option value="">Choose…</option>'+''.join('<option value="'+html.escape(k,quote=True)+'">'+html.escape(v)+'</option>' for k,v in options)
        supplied='<details><summary>Supplied presentation and treatments</summary><pre>'+html.escape(json.dumps(dict(current_presentation=b['current_presentation'],candidates=b['candidates'],evidence=b.get('evidence',[])),indent=2))+'</pre></details>'
        supplied+=''.join('<button type="button" onclick="showStyle(\''+kind+'-pop\')">Watch 5-second '+html.escape(FAMILIES[kind][0])+' example</button>' for kind in dict.fromkeys(c['kind'] for c in b['candidates']))
        missing='<p>No complete supplied treatment. You can still mark that a graphic would help.</p>' if not b['candidates'] else ''
        label_rows.append('<tr><td>'+html.escape(b['id'])+f'<br><button onclick="document.querySelector(\'video\').currentTime={b["start_ms"]/1000};document.querySelector(\'video\').play()">Watch beat</button></td><td>'+html.escape(b['narration'])+supplied+'</td><td><label>Would a graphic help?<select id="op-'+str(i)+'">'+op+'</select></label><label>Which supplied treatment?<select id="tx-'+str(i)+'">'+tx+'</select></label>'+missing+'</td></tr>')
    common='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:17px system-ui;max-width:1200px;margin:30px auto;padding:0 18px}video{width:100%;max-height:60vh}td,th{padding:12px;border-bottom:1px solid #aaa;text-align:left}label{display:block;margin-bottom:12px}select{display:block;max-width:360px;padding:8px}pre{white-space:pre-wrap;max-width:650px}p{line-height:1.5}</style>'
    (folder/'review.html').write_text(common+'<title>Short editing study</title><h1>'+html.escape(study['title'])+'</h1><p>Recommendation-only experiment. Motion is pop. No timeline changes or finalization are enabled.</p><p><a href="calibration.html">Label both stages without model predictions</a></p><video controls src="'+html.escape(media.as_uri(),quote=True)+'"></video><table><tr><th>Beat</th><th>Narration</th><th>Graphic role</th><th>Treatment fit</th></tr>'+''.join(rows)+'</table>',encoding='utf8')
    # Store only identifiers in the label form; predictions stay in the review report.
    data=dict(study_sha256=digest(study),labels=[dict(id=b['id'],opportunity_context_sha256=report['decisions'][b['id']].get('opportunity',{}).get('context_sha256'),treatment_context_sha256=report['decisions'][b['id']].get('treatment',{}).get('context_sha256')) for b in study['beats']])
    payload=json.dumps(data,ensure_ascii=True).replace('<','\\u003c')
    script="""<script>function saveLabels(){const d=JSON.parse(document.getElementById('labels').textContent);d.labels.forEach((r,i)=>{r.opportunity=document.getElementById('op-'+i).value||null;r.treatment=document.getElementById('tx-'+i).value||null;});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));a.download='short-study-labels.json';a.click();URL.revokeObjectURL(a.href);}</script>"""
    (folder/'calibration.html').write_text(common+'<title>Short-study creator choices</title><h1>Label the two questions separately</h1><p>Every beat can be marked as benefiting from a graphic, even when the planner has supplied no treatment. Graphic usefulness and the decision to replace the current presentation are separate questions. All proposed motion is pop.</p><video controls src="'+html.escape(media.as_uri(),quote=True)+'"></video><button onclick="saveLabels()">Download creator labels</button><table>'+''.join(label_rows)+'</table><script id="labels" type="application/json">'+payload+'</script>'+script+preview_ui(folder),encoding='utf8')
    save_json(folder/'creator-labels.template.json',data)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--labels',type=Path)
    args=parser.parse_args();result=run_study(args.input,args.out,args.labels);print(json.dumps(dict(model_requests=result['model_requests'],deployment_enabled=False)))
