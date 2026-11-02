# SPDX-License-Identifier: MIT OR Apache-2.0
"""Import creator labels and analyze the historic trial without inference or edits."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import shutil

from editing_recipe import calibration_gate,file_hash,read,save_json


def family(choice):
    if choice in {'keep','none-of-these','progressive','comparison','source-card'}:return choice
    return choice.rsplit('-',1)[0]


def analyze(recipe,records,labels):
    if labels.get('criteria_sha256')!=recipe['criteria_sha256']:raise ValueError('Labels use different frozen criteria')
    windows={p['id']:p for p in recipe['windows']};seen=set();live=[];fallback=[]
    for row in labels['labels']:
        key=row['id']
        if key in seen or key not in windows:raise ValueError('Unknown or duplicate creator label')
        seen.add(key);record=records[key]
        if row.get('context_sha256')!=record['context_sha256']:raise ValueError('Creator label uses a stale decision context')
        if row['choice'] not in windows[key]['options'] or type(row.get('supported')) is not bool:raise ValueError('Invalid creator choice')
        item=dict(id=key,creator=row['choice'],model=record['assessment']['choice'],supported=row['supported'])
        (live if 'response' in record else fallback).append(item)
    wanted=[r for r in live if r['creator'] not in {'keep','none-of-these'}]
    exact=sum(r['creator']==r['model'] for r in live);by_family=sum(family(r['creator'])==family(r['model']) for r in live)
    choices=dict(Counter(r['choice'] for r in labels['labels']))
    return dict(labels=len(seen),expected_labels=len(windows),creator_choices=choices,supported_checks=sum(r['supported'] for r in labels['labels']),
        live_model=dict(count=len(live),exact_matches=exact,exact_agreement=exact/len(live) if live else None,
            family_matches=by_family,family_agreement=by_family/len(live) if live else None,
            creator_wanted_visual=len(wanted),model_kept_when_creator_wanted_visual=sum(r['model']=='keep' for r in wanted),rows=live),
        planner_only=dict(count=len(fallback),choices=dict(Counter(r['creator'] for r in fallback)),rows=fallback),
        opportunity_detection=dict(measured=False,reason='Candidate availability was determined by the planner. Forced keep/review rows cannot measure visual-opportunity recall.'),
        calibration=calibration_gate(records,labels,recipe['criteria_sha256']),deployment_enabled=False,model_calls=0)


def import_feedback(folder,labels_path):
    recipe=read(folder/'editing-recipe.json');report=read(folder/'preview-report.json');labels=read(labels_path)
    result=analyze(recipe,report['decisions'],labels)
    target=folder/'calibration-labels.json'
    if target.exists() and file_hash(target)!=file_hash(labels_path):raise ValueError('Earlier creator labels exist; preserve them before importing a different review')
    if not target.exists():shutil.copy2(labels_path,target)
    save_json(folder/'creator-feedback.json',dict(result,labels_sha256=file_hash(target)))
    rows=[]
    windows={p['id']:p for p in recipe['windows']}
    for row in result['live_model']['rows']:
        rows.append('<tr><td>'+html.escape(row['id'])+'</td><td>'+html.escape(windows[row['id']]['narration'])+'</td><td>'+html.escape(row['creator'])+'</td><td>'+html.escape(row['model'])+'</td></tr>')
    (folder/'creator-feedback.html').write_text('<!doctype html><meta charset="utf-8"><title>Creator feedback analysis</title><style>body{font:17px system-ui;max-width:1200px;margin:30px auto;padding:0 20px}td,th{padding:12px;border-bottom:1px solid #bbb;text-align:left}p{line-height:1.5}</style><h1>Historical review: no deployment</h1><p>'+str(result['labels'])+' creator choices imported. Motion preference for future experiments: pop.</p><p>'+str(len(result['live_model']['rows']))+' windows received live model judgments. Exact agreement: '+str(result['live_model']['exact_matches'])+'/'+str(result['live_model']['count'])+'. Other rows were planner fallbacks and are excluded from model agreement.</p><p>'+html.escape(result['opportunity_detection']['reason'])+'</p><p>The model selected keep in '+str(result['live_model']['model_kept_when_creator_wanted_visual'])+' windows where the creator requested a treatment. Next studies will separately assess whether a graphic is useful and which supplied treatment fits. No accuracy guarantee or deployment approval follows from this historical review.</p><table><tr><th>Beat</th><th>Narration</th><th>Creator</th><th>Model</th></tr>'+''.join(rows)+'</table>',encoding='utf8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--review',type=Path,required=True);parser.add_argument('--labels',type=Path,required=True)
    args=parser.parse_args();r=import_feedback(args.review,args.labels)
    print(json.dumps({k:v for k,v in r.items() if k in ['labels','creator_choices','calibration','deployment_enabled']}))
