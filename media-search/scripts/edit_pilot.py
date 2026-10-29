# SPDX-License-Identifier: MIT OR Apache-2.0
"""Draft once, review footage, revise the same Editing Script, render comparison previews."""
import argparse
import copy
import json
import re
from pathlib import Path
from pilot import Model, current, digest, duration, file_hash, num, proxy, read, run, save

PRESETS = {
    'none': 'No effect. Prefer when the shot already does the job.',
    'punch': 'Anchor-relative 0.2s eased push from 100 to 112 percent, then hold.',
    'drift': 'Gentle 100 to 105 percent push over the chosen duration.',
    'title': 'Text rises 18px and fades in over 0.25s, with a 0.2s exit fade.',
    'stamp': 'Verdict text settles in five size steps over 0.2s, then holds.',
    'callout': 'Dim picture and mark a normalized rectangular target. Requires visible target.',
}


def validate_edit(edit, cue):
    if edit.get('preset') not in PRESETS:
        raise ValueError('Unknown preset')
    start = num(edit.get('start'), cue['start'], cue['end'])
    seconds = num(edit.get('seconds'), 0.25, min(8, cue['end']-start))
    if not isinstance(edit.get('reason'), str) or not edit['reason'].strip():
        raise ValueError('An edit needs a reason')
    text = edit.get('text', '')
    if text is None and edit['preset'] not in ('title','stamp'):
        text = ''
    if not isinstance(text, str) or len(text) > 100 or any(len(l)>32 for l in text.splitlines()) or len(text.splitlines())>3:
        raise ValueError('Card text exceeds three lines of 32 characters / 100 total')
    if edit['preset'] in ('title', 'stamp') and not text.strip():
        raise ValueError('Missing card text')
    rect = edit.get('rect') or [0.25, 0.25, 0.5, 0.5]
    if not isinstance(rect, list) or len(rect) != 4:
        raise ValueError('Invalid rectangle')
    x, y, w, h = [num(v, 0, 1) for v in rect]
    if not w or not h or x+w > 1 or y+h > 1:
        raise ValueError('Rectangle outside frame')
    return {'preset': edit['preset'], 'start': start, 'seconds': seconds, 'text': text,
            'rect': rect, 'reason': edit['reason'][:1000]}


def validate_plan(plan, snapshot):
    original = {c['id']: c for c in snapshot['cues']}
    if len(plan['cues']) != len(original) or {c['id'] for c in plan['cues']} != set(original):
        raise ValueError('Missing, duplicated, or unknown cues')
    if [c['id'] for c in plan['cues']] != list(original):
        raise ValueError('Cue order changed')
    for c in plan['cues']:
        old = original[c['id']]
        if c['narration'] != old['narration'] or c['start'] != old['start'] or c['end'] != old['end']:
            raise ValueError('Narration or aligned timing changed')
        if c['match'] != old.get('details', {}).get('match', 'subject') or c['method'] != old['method']:
            raise ValueError('Match requirement or production method changed')
        if not isinstance(c['purpose'], str) or not c['purpose'].strip():
            raise ValueError('Missing visual purpose')
        if not isinstance(c['required'], list) or not c['required'] or any(not isinstance(x, str) or not x.strip() for x in c['required']):
            raise ValueError('Missing requirements')
        if c['match'] == 'exact' and old['direction'] not in c['required']:
            raise ValueError('Original exact requirement must remain intact')
        c['edit'] = validate_edit(c['edit'], c)
        labels = '\n'.join(re.findall(r'^TEXT: (.+)$', old['direction'], re.M))
        if labels and (c['edit']['preset'] not in ('title','stamp') or c['edit']['text'] != labels):
            raise ValueError('Visual Script evidence labels must be preserved verbatim')
    return plan


def load_plan(work, name='editing.md'):
    text = (work/name).read_text('utf-8')
    matches = re.findall(r'<!-- pilot-edit (.*?) -->', text)
    if len(matches) != 1:
        raise ValueError('Editing Script must have exactly one pilot-edit record')
    return validate_plan(json.loads(matches[0]), current(work))


def write_plan(work, plan, initial=False):
    validate_plan(plan, current(work))
    text = '# Editing Script\n\nPilot only. Times are chapter-relative seconds; narration is read-only.\n\n'
    text += '| Cue | Time | Purpose | Treatment | Reason |\n|---|---|---|---|---|\n'
    clean = lambda s: str(s).replace('|', '/').replace('\n', ' ')
    for c in plan['cues']:
        e = c['edit']
        text += f'| {c["id"]} | {e["start"]:.2f} | {clean(c["purpose"])} | {e["preset"]} | {clean(e["reason"])} |\n'
    text += '\n<!-- pilot-edit ' + json.dumps(plan, ensure_ascii=False).replace('-->', '--\\u003e') + ' -->\n'
    # The table is a human-readable view. The record is authoritative for this experimental document.
    path = work/'editing.md'
    if initial:
        (work/'editing.initial.md').write_text(text, 'utf-8')
    elif path.exists():
        archive = work/'history'
        archive.mkdir(exist_ok=True)
        (archive/(file_hash(path)+'.md')).write_bytes(path.read_bytes())
    tmp = work/'editing.md.tmp'
    tmp.write_text(text, 'utf-8')
    tmp.replace(path)


def draft(work, model):
    s = current(work)
    if (work/'editing.md').exists():
        raise ValueError('Editing Script already exists; use review to revise it')
    prompt = ('Create the initial visual-intent and Editing Script for this chapter, without rewriting or reviewing '
              'the narration or its beats. Respect every visual constraint. Pick restrained treatments, including none. '
              'At most one treatment per cue. Use chapter-relative seconds within the cue. '
              'Return JSON {cues:[{id,purpose,required:[literal visual requirements],edit:{preset,start,seconds,text,rect,reason}}]}. '
              'Each required predicate must describe observable content; preserve context and evidence labels. '
              'rect is [x,y,width,height] normalized within frame; only use callout if a target can later be verified. '
              'Text <=3 lines, <=32 characters per line. Keep existing TEXT qualifiers verbatim; do not create new claims. '
              'Durations 0.25..8 seconds; start+seconds <= cue.end.\n' + json.dumps({'presets': PRESETS, 'cues': s['cues']}))
    answer = model.ask('draft-editing', prompt)
    if not isinstance(answer.get('cues'), list):
        raise ValueError('Invalid draft')
    by_id = {c['id']: c for c in answer['cues']}
    if len(answer['cues']) != len(s['cues']) or set(by_id) != {c['id'] for c in s['cues']}:
        raise ValueError('Draft cue IDs do not match')
    result = {'version': 1, 'revision': 0, 'presets_revision': digest(PRESETS), 'cues': []}
    for c in s['cues']:
        new = by_id[c['id']]
        labels = '\n'.join(re.findall(r'^TEXT: (.+)$', c['direction'], re.M))
        if labels:
            new['edit']['text'] = labels
            new['edit']['preset'] = 'title'
        required = list(new['required'])
        if c.get('details', {}).get('match') == 'exact' and c['direction'] not in required:
            required.append(c['direction'])
        result['cues'].append({'id': c['id'], 'narration': c['narration'], 'method': c['method'],
                              'start': c['start'], 'end': c['end'], 'subject': c.get('details', {}).get('Subject'),
                              'match': c.get('details', {}).get('match', 'subject'), 'required': required,
                              'purpose': new['purpose'], 'edit': new['edit'], 'locked': False})
    write_plan(work, result, initial=True)


def apply_changes(plan, changes, window):
    result = copy.deepcopy(plan)
    by_id = {c['id']: c for c in result['cues']}
    seen = set()
    for change in changes:
        cue_id = change.get('id')
        if cue_id not in by_id or cue_id in seen:
            raise ValueError('Unknown or repeated edit ID')
        seen.add(cue_id)
        cue = by_id[cue_id]
        if cue.get('locked'):
            raise ValueError('Review attempted to change a locked edit')
        if not cue['start'] < window[1] or not cue['end'] > window[0]:
            raise ValueError('Edit lies outside inspected window')
        observed = num(change.get('observed_at'), 0, window[1]-window[0]) + window[0]
        if not cue['start'] <= observed <= cue['end']:
            raise ValueError('Evidence timestamp is outside cue')
        if not isinstance(change.get('observation'), str) or not change['observation'].strip():
            raise ValueError('Missing observed evidence')
        cue['edit'] = validate_edit(change['edit'], cue)
        cue['review'] = {'at': observed, 'observation': change['observation']}
    result['revision'] += 1
    return result


def review(work, model, start, seconds):
    s, plan = current(work), load_plan(work)
    video = work/'selected.mp4'
    if not video.exists():
        raise ValueError('Render selected first: Gemini needs actual timed picture and voice')
    stamp = read(work/'selected.render.json')
    if stamp['snapshot'] != digest(s) or stamp['selection'] != file_hash(work/'selection.json'):
        raise ValueError('Selected assembly is stale; render again')
    start = num(start, 0, s['duration'])
    end = min(s['duration'], start+num(seconds, 1, 120))
    key = digest([file_hash(video), start, end])
    clip = proxy(video, start, end, work/f'review-{key}.mp4', audio=True)
    cues = [c for c in plan['cues'] if c['start'] < end and c['end'] > start]
    prompt = ('Review this plain timed assembly against its planned Editing Script. Do not rewrite narration or beats. '
              'Planned title cards, zooms, stamps and callouts have NOT been applied yet. Do not flag their absence '
              'as missing assets: assess whether the planned treatment will work over this actual footage. '
              'Preserve useful decisions; no change is valid. Suggest only available presets. A moving shot may need none. '
              'Do not add facts or weaken requirements. Preserve text evidence qualifiers. '
              'Return JSON {changes:[{id,observed_at,observation,edit:{preset,start,seconds,text,rect,reason}}],'
              'issues:[{id,kind:"replacement-footage|script-issue|missing-asset",reason}]}. '
              'observed_at is RELATIVE to this supplied video. edit.start is CHAPTER-relative. '
              'Only edits whose cues overlap the window can change; locked edits must not change. '
              'Report bad footage as an issue, never pretend an effect fixes relevance.\n' + json.dumps({
                  'window_start': start, 'window_end': end, 'cues': cues, 'presets': PRESETS,
                  'coverage': stamp['substitutions']}))
    answer = model.ask('review-editing', prompt, [clip], fps=1)
    if not isinstance(answer.get('changes'), list) or not isinstance(answer.get('issues'), list):
        raise ValueError('Invalid review response')
    for issue in answer['issues']:
        if issue.get('id') not in {c['id'] for c in cues} or issue.get('kind') not in ('replacement-footage','script-issue','missing-asset') or not isinstance(issue.get('reason'),str):
            raise ValueError('Review issue refers to an unknown cue or issue type')
    revised = apply_changes(plan, answer['changes'], [start, end])
    revised['review_basis'] = {'video_sha': file_hash(video), 'window': [start, end], 'plan_before': digest(plan)}
    save(work/f'review-{digest([plan, key])}.json', answer)
    write_plan(work, revised)
    print(f'{len(answer["changes"])} changes; {len(answer["issues"])} issues retained')


def segments(snapshot, selected):
    """Baseline coverage with one verified replacement per cue; never loop to claim coverage."""
    slots = copy.deepcopy(snapshot['baseline'])
    substitutions = []
    for c in snapshot['cues']:
        v = selected.get(c['id'], {})
        if v.get('status') != 'verified':
            continue
        if file_hash(v['path']) != v['sha']:
            raise ValueError('Selected clip changed')
        a, b = c['start'], min(c['end'], c['start']+v['out']-v['in'])
        new_slots = []
        for slot in slots:
            if slot['end'] <= a or slot['start'] >= b:
                new_slots.append(slot)
                continue
            if slot['start'] < a:
                new_slots.append({**slot, 'end': a})
            if slot['end'] > b:
                new_slots.append({**slot, 'start': b, 'in': slot['in']+b-slot['start']})
        slots = new_slots + [{'path': v['path'], 'start': a, 'end': b, 'in': v['in']}]
        substitutions.append({'cue': c['id'], 'start': a, 'end': b, 'status': 'verified-window-only'})
    output, at = [], 0
    for slot in sorted(slots, key=lambda x:x['start']):
        if slot['start'] < at-0.02:
            raise ValueError('Overlapping baseline picture slots')
        if slot['start'] > at+0.001:
            output.append({'path': None, 'start': at, 'end': slot['start'], 'in': 0})
        output.append(slot)
        at = slot['end']
    if at < snapshot['duration']:
        output.append({'path': None, 'start': at, 'end': snapshot['duration'], 'in': 0})
    return output, substitutions


def filters(work, slot, edits):
    vf = ['fps=24', 'scale=960:540:force_original_aspect_ratio=decrease',
          'pad=960:540:(ow-iw)/2:(oh-ih)/2', 'setsar=1']
    for c in edits:
        e = c['edit']
        a, b = e['start']-slot['start'], e['start']+e['seconds']-slot['start']
        if b <= 0 or a >= slot['end']-slot['start'] or e['preset'] == 'none':
            continue
        t = f'(t-({a:.6f}))'
        enable = f'between(t,{a:.6f},{b:.6f})'
        if e['preset'] in ('punch', 'drift'):
            progress = f'min(1,max(0,(on/24-({a:.6f}))/{0.2 if e["preset"]=="punch" else e["seconds"]}))'
            z = f'if(between(on/24,{a:.6f},{b:.6f}),1+{0.12 if e["preset"]=="punch" else 0.05}*({progress})*(2-({progress})),1)'
            vf.append(f"zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=960x540:fps=24")
        elif e['preset'] in ('title', 'stamp'):
            name = f'text-{digest(e["text"])}.txt'
            (work/name).write_text(e['text'], 'utf-8')
            y = f'(h-text_h)/2+18*(1-min(1,max(0,{t}/0.25)))' if e['preset']=='title' else '(h-text_h)/2'
            alpha = f'min(1,max(0,{t}/0.25))*min(1,max(0,({b:.6f}-t)/0.2))'
            steps = [(40,a,b)] if e['preset']=='title' else [(44-k,a+k*.05,min(b,a+(k+1)*.05) if k<4 else b) for k in range(5)]
            for size, left, right in steps:
                gate = f'gte(t,{left:.6f})*lt(t,{right:.6f})'
                vf.append(f"drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':textfile={name}:expansion=none:fontsize={size}:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y='{y}':alpha='{alpha}':enable='{gate}'")
        elif e['preset']=='callout':
            x,y,w,h = e['rect']
            vf += [f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.25:t=fill:enable='{enable}'",
                   f"drawbox=x={x*960}:y={y*540}:w={w*960}:h={h*540}:color=yellow:t=3:enable='{enable}'"]
    return ','.join(vf)


def render(work, variant):
    s = current(work)
    selected = read(work/'selection.json') if variant!='baseline' else {}
    if variant=='baseline':
        edits = []
    elif variant=='selected':
        edits = []
    else:
        plan = load_plan(work, 'editing.initial.md' if variant=='planned' else 'editing.md')
        if variant=='revised' and plan.get('review_basis', {}).get('video_sha') != file_hash(work/'selected.mp4'):
            raise ValueError('Editing review is stale for this selected assembly; run review before revised rendering')
        edits = plan['cues']
    slots, substitutions = segments(s, selected)
    rendered = []
    for i, slot in enumerate(slots):
        length = slot['end']-slot['start']
        if length < 1/24:
            continue
        name = f'{variant}-{i:04}.mp4'
        dest = work/name
        args = ['ffmpeg', '-v', 'error', '-y']
        if slot['path']:
            args += ['-ss', slot['in'], '-i', slot['path']]
            if slot['in']+length > duration(slot['path'])+0.1:
                raise ValueError('Baseline exceeds source handles; refusing to freeze or loop silently')
        else:
            args += ['-f', 'lavfi', '-i', 'color=c=0x202030:s=960x540:r=24']
        vf = filters(work, slot, edits)
        frames = round(slot['end']*24)-round(slot['start']*24)
        args += ['-frames:v', frames, '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p', name]
        run(args, cwd=work)
        rendered.append(name)
    concat = work/f'{variant}.concat.txt'
    concat.write_text(''.join(f"file '{name}'\n" for name in rendered), 'utf-8')
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', concat.name,
         '-i', s['voice'], '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
         '-t', s['duration'], f'{variant}.mp4'], cwd=work)
    save(work/f'{variant}.render.json', {'snapshot': digest(s), 'selection': file_hash(work/'selection.json') if variant!='baseline' else None,
                                        'substitutions': substitutions, 'edits': digest(edits),
                                        'note': 'Unreplaced regions retain baseline; gaps are dark placeholders. No music/captions pass.'})
    print(str(work/f'{variant}.mp4'))


def showcase(work):
    current(work)
    source = work/'baseline.mp4'
    if not source.exists():
        raise ValueError('Render baseline first')
    names = []
    for preset in PRESETS:
        if preset=='none':
            continue
        e = {'preset':preset,'start':0.5,'seconds':3.5,'text':preset.upper(),
             'rect':[.3,.25,.4,.5],'reason':'Preset preview'}
        vf = filters(work,{'start':0.,'end':5.},[{'edit':e}])
        name = f'preset-{preset}.mp4'
        run(['ffmpeg','-v','error','-y','-i',source,'-t','5','-an','-vf',vf,
             '-c:v','libx264','-preset','veryfast','-crf','24',name],cwd=work)
        names.append(name)
    (work/'presets.concat.txt').write_text(''.join(f"file '{name}'\n" for name in names),'utf-8')
    run(['ffmpeg','-v','error','-y','-f','concat','-safe','1','-i','presets.concat.txt','-c','copy','presets.mp4'],cwd=work)
    print(str(work/'presets.mp4'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['draft', 'review', 'render', 'showcase'])
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--model', default='gemini-3.8-flash')
    p.add_argument('--max-calls', type=int, default=1)
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--seconds', type=float, default=90)
    p.add_argument('--variant', choices=['baseline', 'selected', 'planned', 'revised'], default='baseline')
    a = p.parse_args()
    if a.command=='showcase':
        showcase(a.work.resolve())
    elif a.command=='render':
        render(a.work.resolve(), a.variant)
    elif a.command=='draft':
        draft(a.work, Model(a.work, a.model, a.max_calls))
    else:
        review(a.work, Model(a.work, a.model, a.max_calls), a.start, a.seconds)


if __name__=='__main__':
    main()
