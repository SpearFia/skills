# SPDX-License-Identifier: MIT OR Apache-2.0
"""Stage 3 coverage and reproducible representative/miss-review contact sheets."""
import html
import json
import subprocess
import textwrap
import argparse
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from stage3_index import digest, subtract, union
from stage3_sources import save_json


def stamp(seconds):
    return f"{int(seconds)//3600:02}:{int(seconds)//60%60:02}:{seconds%60:06.3f}"


def source_links(rows):
    return '<p>'+ ' · '.join(f"<a href='https://www.youtube.com/watch?v={r['video_id']}&amp;t={int(r['start'])}s'>"+
        html.escape(r.get('kind',r.get('purpose','example'))+' '+r['video_id']+' '+stamp(r['start']))+'</a>' for r in rows)+'</p>'


def thumbnail(video, seconds, directory):
    path = directory/(digest([video['id'],seconds,video.get('crop')])+'.jpg')
    if not path.exists():
        crop = video.get('crop')
        filters = (f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else '')+'scale=320:-2'
        data = subprocess.check_output(['ffmpeg','-v','error','-ss',str(seconds),'-i',video['path'],
            '-frames:v','1','-vf',filters,'-f','image2pipe','-vcodec','mjpeg','-'],timeout=30)
        path.write_bytes(data)
    image = Image.open(path).convert('RGB')
    gray = list(image.convert('L').resize((64,36)).getdata())
    if sum(p <= 7 for p in gray)/len(gray) >= .995:
        return None
    return ImageOps.pad(image,(320,180),color='#303942')


def sheets(rows, videos, directory, stem, heading):
    frames = directory/'frames'
    frames.mkdir(exist_ok=True)
    regular = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14)
    saved, omitted = [], 0
    for page in range(max(1,(len(rows)+5)//6)):
        subset = rows[page*6:page*6+6]
        sheet = Image.new('RGB',(1280,90+max(1,len(subset))*235),'#101820')
        draw = ImageDraw.Draw(sheet)
        draw.text((12,12),heading,font=regular,fill='white')
        draw.text((12,40),'Context 32,768 | original source times | cropped nonblack frames | choice results are model outputs',font=small,fill='#d8e1eb')
        if not subset:
            draw.text((12,105),'No eligible examples. See coverage and download failures; no substitute image was selected.',font=regular,fill='#ffcc80')
        for i,row in enumerate(subset):
            y = 90+i*235
            times = row.get('frame_times',[row['start']+(row['end']-row['start'])*.25,row['start']+(row['end']-row['start'])*.75])
            for j,t in enumerate(times):
                try:
                    picture = thumbnail(videos[row['video_id']],t,frames)
                except (subprocess.SubprocessError,OSError) as exc:
                    picture = None
                    row['thumbnail_error'] = str(exc)
                if picture is not None:
                    sheet.paste(picture,(j*320,y))
                else:
                    omitted += 1
                    draw.text((10+j*320,y+50),'Frame omitted: black or unavailable',font=small,fill='#ffcc80')
                draw.text((5+j*320,y+184),stamp(t),font=small,fill='white')
            p = row.get('probability',row.get('grounding',0))
            title=f"{row.get('kind',row.get('purpose',''))} | {row['video_id']} | {stamp(row['start'])}-{stamp(row['end'])}"
            draw.text((8,y+209),title,font=small,fill='#d8e1eb')
            details=[f"{row['need_id']} | grounding {p:.4f}",
                'Source: '+textwrap.shorten(videos[row['video_id']].get('title',''),width=76,placeholder='…')]
            if 'round' in row:
                details.append(f"Round {row['round']} | threshold {row['threshold']:.2f}")
            choice = row.get('choice') or (row if 'probabilities' in row else None)
            if choice:
                details.append(('CHOICE PASS' if choice['choice_pass'] else 'CHOICE FAIL')+' | target '+chr(65+choice['right_index'])+' | chosen '+chr(65+choice['answer_index']))
                if choice['start']!=row['start'] or choice['end']!=row['end']:
                    details.append('Choice context: '+stamp(choice['start'])+'-'+stamp(choice['end']))
                for option,probability in zip(choice['options'],choice['probabilities']):
                    details.extend(textwrap.wrap(f"{option}  p={probability:.4f}",72))
                scope_labels={'conflict':'Different film in title: excluded','title_matches_group':'Title matches assigned film',
                    'mixed_films_review_required':'Compilation: verify film for this span',
                    'official_source_review_required':'Verify official promotional footage',
                    'scope_review_required':'Source restrictions need review',
                    'creator_group_not_independently_verified':'Pasted film/game group; verify source'}
                details.append('Scope: '+scope_labels[choice['source_scope_status']])
                if 'qc_flags' in choice:
                    details.append('QC flags: '+(', '.join(choice['qc_flags']) or 'none'))
                if choice.get('quality'):
                    q=choice['quality']
                    details.append(f"Quality: {q['category']} | normal p={q['category_probabilities']['normal']:.4f}")
                if row.get('cached_completed_choice'):
                    details.append('Cached choice from completed video; no new inference.')
            elif row.get('choice_unavailable_reason'):
                details.extend(textwrap.wrap(row['choice_unavailable_reason'],72))
                details.extend(chr(65+i)+'. '+option+' | p=not run' for i,option in enumerate(row['choice_options']))
            else:
                details.append('Cell has no separate choice test; candidate confirmations are in candidates.json.')
            if row.get('coarse_dropped_seconds'):
                details.append(f"Coarse dropped {row['coarse_dropped_seconds']:.3f}s, including padding in comparison")
                coarse=row.get('coarse_cell_scores',[])
                if coarse:
                    details.append(f"Coarse p range {min(c['p'] for c in coarse):.4f}-{max(c['p'] for c in coarse):.4f}; black masks {sum(c['black'] for c in coarse)}")
            draw.multiline_text((658,y+3),'\n'.join(details),font=small,fill='white',spacing=3)
        path=directory/f'{stem}-{page+1}.jpg'
        sheet.save(path,quality=90)
        saved.append(path.name)
    return saved,omitted


def render(project,videos,needs,inputs,candidates,representatives,downloads,state,audit_plan):
    folder=project/'media'/'jev'
    score_windows=json.loads((folder/'score-windows.json').read_text(encoding='utf-8'))
    if any(needs[r['need_id']].get('hard') and not r.get('choice') and not r.get('choice_unavailable_reason') for r in representatives):
        raise ValueError('Every displayed hard-need example requires a complete choice result')
    review=project/'production'/'jev-review'
    review.mkdir(parents=True,exist_ok=True)
    doc=["<!doctype html><meta charset='utf-8'><title>Stage 3 VideoJev review</title>",
        "<style>body{font:16px system-ui;max-width:1400px;margin:30px auto;padding:0 16px;color:#17202a}img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccc;text-align:left}summary{font-size:22px;cursor:pointer;padding:12px}.note{background:#fff3bf;padding:16px}</style>",
        '<h1>Stage 3 gate: inspect before assignment</h1>',
        "<p class='note'>Grounding/choice probabilities are model confidence, not verified accuracy. Random above-threshold cells and nearest below-threshold cells are shown, including failures. Cropped black frames are omitted. Exact scenes and mixed-film compilations require source/scene review. No assignment or new timeline was made.</p>"]
    coverage=['# Stage 3 coverage','',
        'Stopped before assignment. Seconds needed are narration estimates at 2.6 words/sec. Confirmed seconds below mean the applicable saved policy passed: legacy clip QC for the 21 frozen videos, or main choice plus final quality choice and ffmpeg freeze checks for new pieces. All use the video black scan and exclude explicit film-title conflicts. These are not human-verified scene matches. Repeated ranges within a need/source count once; different needs may overlap.','',
        '[Open representative and miss-check contact sheets](../../production/jev-review/review.html).','',
        '| Need | Needed s | Model-confirmed s | Sources | Coverage / fallback |',
        '| --- | ---: | ---: | ---: | --- |']
    totals={}
    cues={c['id']:c for c in inputs['cues']}
    for key,need in needs.items():
        by_video={}
        for c in candidates:
            if c['need_id']==key and c['purpose']=='main' and c['passed']:
                by_video.setdefault(c['video_id'],[]).append([c['start'],c['end']])
        seconds=sum(b-a for spans in by_video.values() for a,b in union(spans))
        demand=sum(cues[c]['seconds_estimate'] for c in need['cues'])
        totals[key]=dict(needed=demand,confirmed=seconds,sources=len(by_video))
    for key,need in needs.items():
        t=totals[key]
        exact=any(cues[c]['match']=='exact' for c in need['cues'])
        if need.get('manual'):
            status='UNFILLED: handled by hand'
        elif need.get('review_only'):
            status='Optional review control; no timeline demand'
        elif exact:
            status='UNFILLED / exact-scene review required' if t['confirmed'] else 'UNFILLED: no confirmed supply'
        elif t['confirmed'] < t['needed']:
            target=need['fallback']
            status=f"Shortfall; fallback `{target}` has {totals[target]['confirmed']:.1f}s (not assigned)" if target else 'Shortfall; broad root has no further fallback'
        else:
            status='Model supply sufficient; source/visual review required'
        coverage.append(f"| `{key}` | {t['needed']:.1f} | {t['confirmed']:.1f} | {t['sources']} | {status} |")
    coverage += ['', '## All 21 strict exact requirements', '',
        'No fallback may fill these needs. Automatic confirmation checks the visible description, not the complete named scene identity. Until this review gate verifies the required scene, it remains explicitly unfilled. The HUD stays manual.', '',
        '| Need | Required scene | Model-confirmed supply s | Status |','| --- | --- | ---: | --- |']
    for key,need in needs.items():
        for cue in need['cues']:
            if cues[cue]['match']=='exact':
                coverage.append(f"| `{key}` | {cues[cue]['visual'].replace('|','/')} | {totals[key]['confirmed']:.1f} | {'UNFILLED: handled by hand' if need.get('manual') else 'UNFILLED: scene review required'} |")
    failures=[v for v in downloads['videos'] if v['status']!='ready']
    coverage += ['', '## Download failures and blocked sources', '']
    if not failures:
        coverage.append('None. All submitted video IDs downloaded.')
    for v in failures:
        reason=' '.join(v.get('error','').split())
        coverage.append(f"- [{v['id']}]({v['url']}): **{v['status']}** — {reason}")
    for v in downloads['videos']:
        if v.get('below_480p') or v.get('crop_error'):
            coverage.append(f"- `{v['id']}` warning: "+(f"{v['probe']['width']}×{v['probe']['height']} below 480p; " if v.get('below_480p') else '')+v.get('crop_error',''))
    coverage += ['', '## Indexing failures', '']
    coverage += [f"- `{v['id']}`: {v['error']}" for v in state.get('failed_videos',[])] or ['None.']
    doc.append('<h2>Representative sampling</h2><p>Per need/round: up to 3 fixed-seed random cells above the threshold and the 3 nearest cells below it. Fewer examples mean insufficient eligible cells. Hard-need cells have separate complete choice results beside each example.</p>')
    omitted=0
    for key,need in needs.items():
        if need.get('manual'):
            continue
        doc.append('<details><summary>'+html.escape(need['label'])+'</summary>')
        doc.append('<p>Find: '+html.escape(need['query'])+'</p>')
        for number in [1,2,3]:
            rows=[r for r in representatives if r['need_id']==key and r['round']==number]
            names,n=sheets(rows,videos,review,key+f'-r{number}',f"{key} | round {number} | {need['query']}")
            omitted+=n
            above=sum(r['kind']=='random above' for r in rows)
            below=sum(r['kind']=='nearest below' for r in rows)
            doc.append(f'<p>Round {number}: {above}/3 above; {below}/3 below. Missing examples are unavailable/skipped, not replaced with top hits.</p>')
            doc.append(source_links(rows))
            doc.extend(f"<a href='{name}'><img loading='lazy' src='{name}' alt='{key} round {number}'></a>" for name in names)
        doc.append('</details>')
    audit=[c for c in candidates if c['purpose']=='miss_audit']
    retained={}
    for row in score_windows:
        if row['round']==2 and not row['audit']:
            retained.setdefault((row['video_id'],row['need_id']),[]).append([row['start'],row['end']])
    for path in (folder/'coarse-v2').glob('*.json'):
        data=json.loads(path.read_text())
        for need_id,ranges in data['retained'].items():
            retained[(path.stem,need_id)]=ranges
    for candidate in audit:
        # Actual round-2 inputs include coarse padding and question unions from overlapping windows.
        spans=union(retained.get((candidate['video_id'],candidate['need_id']),[]))
        candidate['coarse_retained_windows']=spans
        candidate['coarse_dropped']=subtract(candidate['start'],candidate['end'],spans)
        candidate['coarse_dropped_seconds']=sum(b-a for a,b in candidate['coarse_dropped'])
    confirmed=[c for c in audit if c['passed']]
    misses=[c for c in confirmed if c['coarse_dropped_seconds']>=1.5]
    for candidate in misses:
        candidate['coarse_cell_scores']=[dict(start=row['start']+a,end=row['start']+b,p=p,black=row['black'][i])
            for row in score_windows if row['video_id']==candidate['video_id'] and row['need_id']==candidate['need_id'] and row['round']==1 and not row['audit']
            for i,((a,b),p) in enumerate(zip(row['bounds'],row['probabilities']))
            if row['start']+b>candidate['start'] and row['start']+a<candidate['end']]
    per_source={key:dict(sampled_seconds=sum(b-a for a,b in stretches),
        confirmed_candidate_spans=sum(c['video_id']==key for c in confirmed),
        missed_candidate_spans=sum(c['video_id']==key for c in misses),
        missed_span_seconds=sum(c['coarse_dropped_seconds'] for c in misses if c['video_id']==key)) for key,stretches in audit_plan.items()}
    failed_sources={v['id'] for v in state.get('failed_videos',[])}
    completed_sources=[key for key,stretches in audit_plan.items() if key not in failed_sources and all(
        {r['need_id'] for r in score_windows if r['audit'] and r['video_id']==key and abs(r['start']-a)<1e-5 and abs(r['end']-b)<1e-5}==set(videos[key]['needs'])
        for a,b in stretches)]
    audit_report=dict(plan=audit_plan, audited_sources=len(completed_sources),completed_sources=completed_sources,
        gate_complete=len(completed_sources)>=2,confirmed_candidate_spans=len(confirmed),
        coarse_missed_candidate_spans=len(misses),coarse_missed_seconds=sum(c['coarse_dropped_seconds'] for c in misses),
        per_source=per_source,misses=misses,limitation='Reproducible sampled stretches, not exhaustive recall or shot-boundary detection; confirmation uses the same model.')
    save_json(folder/'miss-audit-report.json',audit_report)
    save_json(folder/'candidates.json',candidates)
    coverage += ['', '## Independent 2 fps miss check','',
        f"Completed independent audits on {len(completed_sources)} distinct long sources, three predetermined 120-second stretches each. {len(confirmed)} candidate spans passed choice/QC/scope checks; {len(misses)} include at least 1.5 seconds outside their need's actual retained coarse windows **including padding and merged question lists**. Missed confirmed span-seconds: {audit_report['coarse_missed_seconds']:.3f} (may overlap across needs).",'',
        'This samples recall; it is not exhaustive and uses the same model for confirmation. `miss-audit-plan.json` was written before coarse processing. V2 uses the planned coarse-retained windows before quota stopping, including direct-to-fine windows for needs that bypass round 2; quota stopping is not a coarse detector miss. `miss-audit-report.json` retains every missed range and complete choice results.','']
    doc.append('<h2>Independent 2 fps miss check</h2><p>'+html.escape(coverage[-4])+'</p>')
    coverage += ['| Source | Independently sampled s | Confirmed spans | Missed spans | Missed span-seconds |',
        '| --- | ---: | ---: | ---: | ---: |']
    for key,counts in per_source.items():
        coverage.append(f"| `{key}` | {counts['sampled_seconds']:.1f} | {counts['confirmed_candidate_spans']} | {counts['missed_candidate_spans']} | {counts['missed_span_seconds']:.3f} |")
    coverage.append('')
    for video_id,stretches in audit_plan.items():
        doc.append('<p>'+html.escape(video_id+': '+', '.join(stamp(a)+'-'+stamp(b) for a,b in stretches))+'</p>')
    names,n=sheets(misses,videos,review,'misses','Confirmed fine-scan spans outside coarse retained windows (padding included)')
    omitted+=n
    doc.append(source_links(misses))
    doc.extend(f"<a href='{name}'><img loading='lazy' src='{name}' alt='Coarse miss review'></a>" for name in names)
    coverage += ['## Hard-need results','', '| Need | Main candidates | Passed | Choice failed | QC failed | Source conflict |','| --- | ---: | ---: | ---: | ---: | ---: |']
    doc.append('<h2>Hard needs: complete multiple-choice results</h2>')
    for key,need in needs.items():
        if not need.get('hard'):
            continue
        rows=[c for c in candidates if c['need_id']==key and c['purpose']=='main']
        coverage.append(f"| `{key}` | {len(rows)} | {sum(c['passed'] for c in rows)} | {sum(not c['choice_pass'] for c in rows)} | {sum(any(f in c['qc_flags'] for f in ['black','frozen']) for c in rows)} | {sum(c['source_scope_status']=='conflict' for c in rows)} |")
        selected=sorted(rows,key=lambda c:-c['score'])[:3]+sorted([c for c in rows if not c['passed']],key=lambda c:-c['score'])[:3]
        selected=list({c['id']:c for c in selected}.values())
        names,n=sheets(selected,videos,review,'hard-'+key,key+': '+need['query'])
        omitted+=n
        doc.append('<h3>'+html.escape(key)+'</h3>')
        doc.append(source_links(selected))
        doc.extend(f"<a href='{name}'><img loading='lazy' src='{name}' alt='{key} full choice results'></a>" for name in names)
    coverage += ['', '## Black filtering, source scope and measurement limits','',
        'Black spans use ffmpeg blackdetect on the cropped active picture: pixel threshold 0.02, picture ratio 0.995, minimum span 0.01 s. Cells containing a black sampled input frame are excluded from evidence; candidates split at source black spans. Frozen legacy videos keep their saved clip QC. New pieces use the final quality question and ffmpeg frozen-only check, without another per-piece black scan or full clip QC. Input context retains its original timeline; no frame deletion collapses timestamps. Thumbnail filtering independently omits nearly pure black images (99.5% of 64×36 grayscale pixels at or below 7). Genuine dark scenes are retained unless they meet these strict rules.','',
        f'Black/unavailable thumbnails omitted: {omitted}. Full score vectors, excluded-cell flags, timing and peak VRAM are in `score-windows.json` and `timing-report.json`; no features were persisted.','',
        'Explicit film-title conflicts are excluded from usable coverage. Compilations, unofficial uploads and uncertain scopes still need review; matching plain visual descriptions cannot establish film identity or exact story context. No assignment, VO timing alignment, master download or timeline build was performed.']
    performance_path=folder/'performance-v2.json'
    if performance_path.exists():
        performance=json.loads(performance_path.read_text())
        missing=sum(bool(r.get('choice_unavailable_reason')) for r in representatives)
        coverage += ['', '## Revised quotas and frozen legacy results','',
            'Twenty-one completed videos retain their original results and clip-QC policy. New pieces use main-query-first search, a 3× narration-seconds target and an initial one-third target cap per source. After all assigned URLs are attempted, short needs may use additional pieces from sources that matched. Variants run only for remaining shortfalls. Accepted new pieces have a four-second minimum gap within the same source/need.','',
            f'{missing} representative cells have no cached choice covering their range on a frozen completed video. Those results are explicitly unavailable; no new model question was run on a completed video. Other frozen representatives show their saved choice context.', '',
            '[First-three speed report](speed-first3.md) · [Logo-option control report](logo-option-report.md).', '',
            '| Need | Target s | Credited s | Source cap lifted |','| --- | ---: | ---: | --- |']
        for key,target in performance['targets'].items():
            coverage.append(f"| `{key}` | {target['target_seconds']:.1f} | {target['credited_seconds']:.1f} | {target['cap_lifted']} |")
        logo_path=folder/'logo-option-report.json'
        if logo_path.exists():
            logo=json.loads(logo_path.read_text())
            coverage += ['',f"Synthetic corner-watermark controls: logo recognized {logo['detected_logo']}/{logo['tested']}; quality gate rejected {logo['rejected']}/{logo['tested']}. "+logo['limitation']]
    # Use the same configured fast cache as the orchestrator, including custom SPEARFIA_CACHE.
    from stage3_sources import pool
    index_cache=pool.cache_dir(project)/'jev-index'
    black_counts={}
    for key in videos:
        path=index_cache/(key+'.black.json')
        ranges=json.loads(path.read_text())['ranges'] if path.exists() else []
        windows={row['window_id']:row for row in score_windows if row['video_id']==key}
        frames=sum(any(a-1e-6 <= row['start']+i/row['fps'] < b-1e-6 for a,b in ranges)
            for row in windows.values() for i in range(row['frames']))
        cells=sum(sum(row['black']) for row in windows.values())
        black_counts[key]=dict(source_black_spans=len(ranges),source_black_seconds=sum(b-a for a,b in ranges),
            excluded_sampled_frames=frames,excluded_score_cells=cells)
    save_json(folder/'black-filter-report.json',black_counts)
    coverage += ['', '### Excluded black evidence', '',
        'Frame/cell counts count each sampled window once, including independent audit windows. The same source moment can be sampled in several rounds.', '',
        '| Source | Black span-seconds | Black sampled frames | Excluded score cells |', '| --- | ---: | ---: | ---: |']
    for key,counts in black_counts.items():
        coverage.append(f"| `{key}` | {counts['source_black_seconds']:.3f} | {counts['excluded_sampled_frames']} | {counts['excluded_score_cells']} |")
    tasks={t['task']:t for t in json.loads((folder/'timing-report.json').read_text(encoding='utf-8'))}
    timing=defaultdict(lambda:dict(sampling=0.,prepare=0.,encode=0.,query=0.,peak=0.))
    for task in tasks.values():
        measured=timing[task['video_id']]
        for output,input_key in [('sampling','sampling_seconds'),('prepare','prepare_seconds'),('encode','encode_seconds')]:
            measured[output]+=task[input_key]
        measured['query']+=sum(q['seconds'] for q in task['queries'])
        measured['peak']=max(measured['peak'],max(q['peak_allocated_mib'] for q in task['queries']))
        raw_path=index_cache/'tasks'/(task['task']+'.result.json')
        if raw_path.exists():
            measured['peak']=max(measured['peak'],json.loads(raw_path.read_text()).get('encode_peak_allocated_mib',0))
    coverage += ['', '## Measured processing time and VRAM', '',
        'Stored unique model tasks are counted once, including reused results after resume. Sampling time is measured when a new window is cut; cached windows add zero. Totals include main search, choices, the miss audit and hard representative choices. Per-question times and allocated/reserved peaks remain in `timing-report.json`.', '',
        '| Source | Sampling s | Preprocess s | Encode s | Questions s | Peak allocated MiB |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for key,t in timing.items():
        coverage.append(f"| `{key}` | {t['sampling']:.2f} | {t['prepare']:.2f} | {t['encode']:.2f} | {t['query']:.2f} | {t['peak']:.1f} |")
    conflicts={}
    for c in candidates:
        if c['source_scope_status']=='conflict':
            conflicts.setdefault(c['video_id'],set()).add(c['need_id'])
    if conflicts:
        coverage += ['', '### Explicit source conflicts', '']
        for key,ids in conflicts.items():
            coverage.append(f"- `{key}` — {videos[key].get('title','')}: excluded for "+', '.join('`'+i+'`' for i in sorted(ids))+'.')
    save_json(folder/'coverage.json',totals)
    (folder/'coverage.md').write_text('\n'.join(coverage)+'\n',encoding='utf-8')
    (review/'review.html').write_text('\n'.join(doc),encoding='utf-8')
    save_json(folder/'review-summary.json',dict(contact_sheets=len(list(review.glob('*.jpg'))),omitted_thumbnails=omitted,misses=len(misses),failed_downloads=len(failures)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    project=parser.parse_args().project
    folder=project/'media'/'jev'
    def read(name):
        return json.loads((folder/name).read_text(encoding='utf-8'))
    downloads=read('download-report.json')
    videos={v['id']:v for v in downloads['videos'] if v['status']=='ready'}
    render(project,videos,{n['id']:n for n in read('needs.json')},read('input-cues.json'),
        read('candidates.json'),read('representatives.json'),downloads,read('index-status.json'),read('miss-audit-plan.json')['sources'])
