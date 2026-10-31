# SPDX-License-Identifier: MIT OR Apache-2.0
"""Resume the approved script-first timeline build, then stop at Stage 4."""
import collections
import os
import shutil
import time
from pathlib import Path

from script_first import approve,read,sha
from script_assignment import Assignment
from stage3_sources import pool,save_json
from stage4_assign import FPS,cut_masters
from stage4_build import build_assignment
from stage4_verify import verify


def replace_footage_links(project,folder):
    backup=folder/'links-before-script-stage4.json'
    if not backup.exists():shutil.copy2(project/'links.json',backup)
    if (folder/'stage4-links.json').exists():return
    current=read(project/'links.json');old=read(backup)
    retained=lambda d:[l for l in d['links'] if not l['media']['path'].replace('\\','/').startswith('B-roll/')]
    if retained(current)!=retained(old):raise ValueError('Non-footage links changed; backup retained for review')
    if current!=old:save_json(folder/('links-before-resume-'+str(time.time_ns())+'.json'),current)
    current['links']=retained(current)
    save_json(project/'links.json',current)


def report(project,folder):
    a=read(folder/'assignment.json');b=read(folder/'stage4-build.json');checks=read(folder/'stage4-verification.json')
    d=read(project/'media/jev/script-first/beats.json');qs=read(project/'media/jev/script-first/questions.json')
    if isinstance(qs,list):qs={q['id']:q for q in qs}
    beats={x['id']:x for x in d['beats']};filled=[s for s in a['slots'] if s['top']];gaps=[s for s in a['slots'] if not s['top']]
    seconds=lambda ss:sum(s['duration_frames'] for s in ss)/FPS
    alt=collections.Counter(len(s['alternates']) for s in filled)
    missing=[]
    bucket=lambda s:(s['kind'],s['question_id'],tuple(s['groups']))
    for kind,qid,groups in dict.fromkeys(bucket(s) for s in gaps):
        ss=[s for s in gaps if bucket(s)==(kind,qid,groups)];q=qs.get(qid,{})
        missing.append(dict(question_id=qid,query=q.get('query','Manual six-slot HUD' if kind=='manual' else 'Unused general footage'),group=q.get('source_group',', '.join(groups)),
            seconds=seconds(ss),times=[round(s['start_frame']/FPS,2) for s in ss],
            beats=list(dict.fromkeys(x for s in ss for x in s['beat_ids'])),kind=ss[0]['kind']))
    mix=[]
    for group in sorted({s['top']['source_group'] for s in filled}):
        ss=[s for s in filled if s['top']['source_group']==group];by_source=collections.Counter()
        for s in ss:by_source[s['top']['video_id']]+=s['duration_frames']/FPS
        near=sum(sum(y-x<60*FPS for x,y in zip(times,times[1:])) for vid in by_source
            for times in [sorted(s['start_frame'] for s in ss if s['top']['video_id']==vid)])
        mix.append(dict(group=group,placed_seconds=seconds(ss),sources=len(by_source),largest_source_share=max(by_source.values())/seconds(ss),within_60s=near))
    result=dict(status='awaiting_creator_stage4_review',review=b['review'],beats=len(beats),slots=len(a['slots']),filled_slots=len(filled),
        filled_seconds=seconds(filled),unfilled_seconds=seconds(gaps),alternate_counts=dict(alt),missing=missing,source_mix=mix,checks=checks,
        duplicate_candidates_rejected=a['duplicate_candidates_rejected'],stage5_started=False)
    save_json(folder/'coverage.json',result)
    lines=['# Script-first Stage 4 review','',f"Review: `{b['review']}`",'',
        f"All {len(beats)} approved sentences were word-timed. {len(filled)}/{len(a['slots'])} slots placed ({seconds(filled):.1f} s); "
        f"{seconds(gaps):.1f} s left empty. {alt[2]} clips have two alternates, {alt[1]} have one, {alt[0]} have none.",'',
        'Specific sentences receive brief literal inserts; remaining narration uses the same film/game general pool. '
        'General footage has no positive-score requirement. Old Subject labels, visual-cue boundaries and duration quotas were not used. '
        'Missing literal inserts remain empty; general footage does not count as proof of them. '
        'Existing cards, narration, music, captions, intro/end and blur remain in the pushed timeline.','',
        'Blocked: `tJbzMqJGH4k` is age-gated; paste a replacement. No bypass or retry. '
        'Only additional URLs containing the missing literal shots below would improve those gaps; covered general remainders proceeded without waiting.','',
        '## Unfilled literal inserts','',
        'A shortage means no remaining unused, model-confirmed range survived quality filtering and the global allocation. '
        'It does not prove that every frame of the source lacks the action. Scene identity still requires creator judgment. '
        'The six-slot HUD stays manual.','',
        '| Group | Visible query | Empty seconds | Timeline seconds |','| --- | --- | ---: | --- |']
    for m in missing:
        lines.append(f"| {m['group']} | {m['query'].replace('|','/')} | {m['seconds']:.1f} | {', '.join(map(str,m['times']))} |")
    if not missing:lines.append('| All | No unfilled slots | 0 | |')
    lines+=['','## General pools and source variety','',
        'Source spacing (60 s) and source share (25%) are preferences that relax when matching supply is limited. '
        'Top footage ranges never overlap in source time. A 2 fps perceptual filter also rejects coherent copies across URLs; this is approximate.','',
        '| Group | Placed seconds | Sources | Largest source share | Same-source placements within 60 s |',
        '| --- | ---: | ---: | ---: | ---: |']
    lines += [f"| {m['group']} | {m['placed_seconds']:.1f} | {m['sources']} | {m['largest_source_share']:.1%} | {m['within_60s']} |" for m in mix]
    bench=checks['render_benchmark']
    lines+=['','## Stage 4 checks','',
        f"- Source and timeline overlap checks passed. {a['duplicate_candidates_rejected']} candidate copies were rejected by perceptual matching.",
        f"- {checks['master_count']} silent, video-only 480p masters. All native clip starts/durations and source offsets passed readback.",
        f"- Handles are 2.5 s; {len(checks['physical_source_clamps'])} placements clamp at physical source ends. Tick scale is {checks['ticks_per_second']:,}/s; 2.5 s is {checks['handle_ticks']:,} ticks.",
        '- Deleting the chosen clip and then alternate 1 in an unsaved copy exposed three distinct rendered frames. The delivered review stayed unchanged.',
        '- Top and alternate footage use native Scale to Frame Size in the 3840×2160 sequence, retaining source aspect ratio.',
        f"- Three-layer 480p render: {bench['content_seconds']:.2f} s content in {bench['wall_seconds']:.2f} s wall time. Interactive playback remains for the creator to check in FilmCraft.",
        '- The original project, links, script and visuals hashes are unchanged. Earlier assignments, masters and reviews are retained.',
        '- Saved native question scores and confirmations were reused. Main-query references bridge older answer wording; variants never inherit a different target. Known source conflicts and quality rejections remain rejected.',
        '- No new model requests, semantic beat edits, Stage 5 commands or 1080p downloads were performed.','',
        '## Evidence','',f"- Assignment and all gap times: `{folder/'assignment.json'}`.",
        f"- Coverage, source variety and checks: `{folder/'coverage.json'}`.",
        f"- Native snapshot and verification: `{folder}`.",
        f"- Render checks: `{project/'production/jev-script-stage4'}`.",'',
        'Stopped at the Stage 4 gate. Open the layered project for playback and visual review.']
    path=project/'production/jev-script-stage4-report.md';path.write_text('\n'.join(lines)+'\n',encoding='utf8')
    return result,path


class Build:
    def __init__(self,project):
        self.project=project;self.document=approve(project);self.root=project/'media/jev/script-first';self.folder=self.root/'stage4';self.folder.mkdir(exist_ok=True)
        self.state=read(self.root/'stage4-run.json') if (self.root/'stage4-run.json').exists() else dict(started=time.time(),timings=[])
        if self.state.get('status')=='script_stage4_gate_ready':
            raise ValueError('Stage 4 is already ready; no rebuild requested')
        self.state.update(status='running',pid=os.getpid(),stage5_started=False);self.state.pop('error',None)
        if not (self.folder/'query-summary-before-stage4.md').exists():
            shutil.copy2(project/'production/jev-script-first-summary.md',self.folder/'query-summary-before-stage4.md')
        names=['beats.json','questions.json','general-pools.json','score-reuse.json','query-results/score-windows.json','query-results/candidates.json']
        manifest={name:sha(self.root/name) for name in names}
        p=self.folder/'input-manifest.json'
        if p.exists() and read(p)!=manifest:raise ValueError('Assignment inputs changed; saved artifacts retained')
        if not p.exists():save_json(p,manifest)
        original=Path(self.document['approved_script']).parent.parent
        self.protected=[original/name for name in ['project.json','links.json','script/script.md','visuals/visuals.md']]
        self.protected += [project/'media/jev'/name for name in ['needs.json','candidates.json','score-windows.json','assignment.json']]
        self.protected += [self.root/name for name in names]
        guard=self.folder/'protected-hashes.json'
        if not guard.exists():save_json(guard,{str(p):sha(p) for p in self.protected})
        self.check_protected()

    def check_protected(self):
        for name,h in read(self.folder/'protected-hashes.json').items():
            if sha(name)!=h:raise ValueError('Protected input changed: '+name)

    def status(self,phase):
        if (self.folder/'stop').exists():raise RuntimeError('Creator requested stop; completed work retained')
        self.state.update(phase=phase,updated=time.time());self.summary();print(phase,flush=True)

    def summary(self):
        self.state['elapsed_seconds']=time.time()-self.state['started'];save_json(self.root/'stage4-run.json',self.state)
        lines=['# Script-first Stage 4 — short summary','',f"Status: **{self.state['status']}**. Phase: {self.state.get('phase','startup')}.",'',
            f"Elapsed: {self.state['elapsed_seconds']/60:.1f} min. No new model queries. Stage 5 has not started.",'',
            'Blocked: `tJbzMqJGH4k` is age-gated; replacement needed. No bypass or retry.']
        if self.state.get('coverage'):
            c=self.state['coverage'];lines+=['',f"Placed {c['filled_slots']}/{c['slots']} slots ({c['filled_seconds']:.1f} s); {c['unfilled_seconds']:.1f} s unfilled. "
                f"Alternates: {c['alternate_counts']}.",'',f"Review: `{self.state['review']}`.",'',f"Report: `{self.state['report']}`.",'',
                'Automatic Stage 4 checks passed. Interactive playback and literal scene identity remain for creator review. Original unchanged.']
        if self.state.get('error'):lines+=['','Error: '+self.state['error'][:1200]]
        (self.project/'production/jev-script-first-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

    def step(self,label,call):
        self.status(label);start=time.perf_counter();result=call()
        self.state['timings'].append(dict(phase=label,seconds=time.perf_counter()-start));self.summary();return result

    def run(self):
        try:
            if not (self.folder/'assignment.json').exists():
                a=Assignment(self.project,self.status)
                self.step('Filter saved specific sources',a.quality_sources)
                self.step('Load source fingerprints',a.hash_sources)
                self.step('Assign approved beats and general pools',a.allocate)
            a=read(self.folder/'assignment.json')
            if not (self.folder/'masters.json').exists():
                videos={v['id']:v for v in read(self.project/'media/jev/download-report.json')['videos'] if v['status']=='ready'}
                self.step('Cut silent handled 480p masters',lambda:cut_masters(self.project,a,videos,self.folder))
            if not (self.folder/'stage4-build.json').exists():
                self.step('Replace demo footage links',lambda:replace_footage_links(self.project,self.folder))
                self.step('Push FilmCraft and add two alternate tracks',lambda:build_assignment(self.project,self.folder,a,Path(self.document['approved_script']).parent.parent))
            if not (self.folder/'stage4-verification.json').exists():
                self.step('Verify native timing, handles, silence and alternate reveal',lambda:verify(self.project,self.folder,self.project/'production/jev-script-stage4'))
            self.check_protected()
            result,path=self.step('Write Stage 4 coverage report',lambda:report(self.project,self.folder))
            self.state.update(status='script_stage4_gate_ready',phase='Stopped before Stage 5',report=str(path),review=result['review'],
                coverage={k:result[k] for k in ['slots','filled_slots','filled_seconds','unfilled_seconds','alternate_counts']})
        except Exception as exc:
            self.state.update(status='script_stage4_failed',error=str(exc));raise
        finally:self.summary()


def run(project):
    import msvcrt
    approve(project);folder=project/'media/jev/script-first/stage4';folder.mkdir(exist_ok=True)
    with (folder/'build.lock').open('a+b') as lock:
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Stage 4 is already running') from exc
        try:Build(project).run()
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
