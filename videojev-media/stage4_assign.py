# SPDX-License-Identifier: MIT OR Apache-2.0
"""Word-timed assignment of confirmed footage, bounded masters and shortage policy."""
import argparse
import collections
import difflib
import json
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stage3_index import digest,subtract
from stage3_sources import command,save_json,pool,qc
from jev import require_legacy

FPS=30
HANDLE=2.5
FC=r'C:\Program Files\FilmCraft\filmcraft-cli.exe'
SPEARFIA=r'C:\dev\spearfia\spearfia\target\release\spearfia.exe'
ROOTS={'wick1':'wick1-action','wick2':'wick2-suit-protection','wick3':'wick3-action','wick4':'wick4-action',
    'gta6':'gta6-coastal-roads','gta5':'gta5-car-chase','gta4':'gta4-police-pursuit','gta3':'gta3-tanks-trucks',
    'gtasa':'gtasa-military-truck','gtavc':'gtavc-military-tanks'}
# A broader fighting query cannot inherit a positive answer about conversation or injury alone.
NON_ACTION_EVIDENCE={'wick1-police-visit','wick1-sniper-help','wick2-leave-car','wick2-wrecked-car',
    'wick2-pistol-supply','wick3-roof-fall','wick3-injured-movement','wick3-armory','wick3-exhausted-zero','wick3-rescued'}
NON_FIGHT_SOURCES={'wick1-action':{'4S8_1PIolnY'},'wick3-action':{'E9B65UGKQ5o'}}
MICRO={'wick1-nightclub-throw':3,'wick2-wrecked-car':4,'wick2-leave-car':3,'wick2-pistol-supply':4,
    'wick2-prepared-escape':5,'wick3-roof-fall':4,'wick3-armory':5,'wick3-rescued':4,'wick3-exhausted-zero':4,
    'wick4-fire-shotgun':4,'wick4-weapon-pickup':3,'wick4-stairs-fall':4,'gta6-enter-car':3,'gta5-vehicle-switch':4,
    'gta5-tactical-suv':4}
# Named scene evidence stays stricter than the broad visual classifier.
EXACT_SOURCES={
    'wick1-home-fight':{'CdHKXmEn4l8'},'wick1-nightclub-movement':{'yu3iX6zxbm0'},'wick1-nightclub-throw':{'yu3iX6zxbm0'},
    'wick2-driving-warehouse':set(),'wick2-wrecked-car':set(),'wick2-pistol-supply':set(),
    'wick2-prepared-escape':{'eVJhlVgr9lM'},'wick3-roof-fall':set(),'wick3-armored-defense':set(),'wick3-armory':set(),
    'wick3-exhausted-zero':set(),'wick3-rescued':{'E9B65UGKQ5o'},'wick4-driving-traffic':{'oa7BjVtvA7w'},
    'wick4-fire-shotgun':set(),'wick4-stairs-fall':{'hrq7sSV3dkA'},'wick4-stairs-allies':{'hrq7sSV3dkA'},
    'gta6-six-slot-hud':set(),'gta5-police-helicopter':set(),'gta5-tactical-suv':set(),
    'gta4-helicopter-pair':None,'gta3-tanks-trucks':None}


def norm(word):
    value=re.sub(r'[^\w]','',word.casefold())
    return {'1':'one','2':'two','3':'three','4':'four','5':'five','6':'six','vi':'six','iv':'four','v':'five'}.get(value,value)


def spoken(line):
    return re.sub(r'\[[^]]+\]\s*','',re.sub(r'^\s*VO:\s*','',line)).replace('**','').replace('*','')


def cue_times(project,cues):
    lines=(project/'script/script.md').read_text(encoding='utf-8').splitlines()
    vo=json.loads((project/'media/vo-words.json').read_text(encoding='utf-8'))
    links=[l for l in pool.links(project) if l.get('role')=='voiceover']
    plan=json.loads(sorted((project/'sync/plans').glob('*.json'),key=lambda p:p.stat().st_mtime)[-1].read_text(encoding='utf-8'))
    items={i['source']['path']:i for i in plan['items'] if i['kind']=='clip' and i['track']=='A1'}
    result={}
    for k,link in enumerate(links):
        last=links[k+1]['line'] if k+1<len(links) else len(lines)
        words=[]; positions={}
        for line in range(link['line'],last):
            if re.match(r'^\s*VO:',lines[line]):
                tokens=spoken(lines[line]).split()
                positions[line]=(len(words),tokens)
                words.extend(tokens)
        heard=vo[link['media']['path']]['words']
        matcher=difflib.SequenceMatcher(None,[norm(w) for w in words],[norm(w[0]) for w in heard],autojunk=False)
        known={a+i:heard[b+i][1] for a,b,n in matcher.get_matching_blocks() for i in range(n)}
        item=items[link['media']['path']]
        duration=item['duration_frames']/FPS
        starts=[]
        for i in range(len(words)):
            if i in known:
                starts.append(known[i])
            else:
                prev=max((j for j in known if j<i),default=-1)
                following=min((j for j in known if j>i),default=len(words))
                lo=known.get(prev,0);hi=known.get(following,duration)
                starts.append(lo+(hi-lo)*(i-prev)/(following-prev))
        starts.append(duration)
        for cue in cues:
            if cue['line'] not in positions:
                continue
            offset,tokens=positions[cue['line']]
            target=[norm(w) for w in cue['quote'].split()]
            normalized=[norm(w) for w in tokens]
            at=next((i for i in range(len(tokens)) if normalized[i:i+len(target)]==target),None)
            if at is None:
                raise ValueError('Cue is not in approved script: '+cue['id'])
            a=round(starts[offset+at]*FPS)+item['start_frame']
            b=round(starts[min(len(words),offset+at+len(target))]*FPS)+item['start_frame']
            if b<=a:
                raise ValueError('Cue has no timed narration: '+cue['id'])
            result[cue['id']]=dict(start_frame=a,end_frame=b,vo_path=link['media']['path'],alignment_fraction=len(known)/max(1,len(words)))
    if set(result)!=set(c['id'] for c in cues):
        raise ValueError('Not every cue was aligned to voiceover')
    return result


def fingerprints(video,cache,a=0,b=None,rate=2):
    b=video['probe']['duration'] if b is None else b
    key=digest([video['id'],video.get('crop'),round(a,6),round(b,6),rate,'rgb-dhash'])
    path=cache/(key+'.hash.json')
    if path.exists():
        return json.loads(path.read_text())
    crop=video.get('crop')
    filters=(f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else '')
    filters+=f'fps={rate}:start_time=0:round=up,scale=17:16,format=rgb24'
    data=subprocess.check_output(['ffmpeg','-v','error','-ss',str(a),'-t',str(b-a),'-i',video['path'],
        '-an','-vf',filters,'-f','rawvideo','-'],timeout=180)
    rows=[]
    for i in range(len(data)//816):
        frame=data[i*816:(i+1)*816]
        gray=[(3*frame[j]+6*frame[j+1]+frame[j+2])//10 for j in range(0,816,3)]
        bits=0
        for y in range(16):
            for x in range(16):bits=(bits<<1)|(gray[y*17+x]>gray[y*17+x+1])
        rows.append(dict(time=a+i/rate,hash=str(bits),color=[sum(frame[c::3])//272 for c in range(3)]))
    save_json(path,rows)
    return rows


class FrameIndex:
    def __init__(self):
        self.frames=[]
        self.bands=collections.defaultdict(list)

    def add(self,frame,source):
        i=len(self.frames);h=int(frame['hash'])
        self.frames.append((frame,source))
        for b in range(16):self.bands[(b,(h>>(b*16))&65535)].append(i)

    def matches(self,frame,exclude=None):
        h=int(frame['hash']);indices=set()
        for b in range(16):indices.update(self.bands.get((b,(h>>(b*16))&65535),[]))
        found=[]
        for i in indices:
            other,source=self.frames[i]
            distance=(h^int(other['hash'])).bit_count()
            if source!=exclude and distance<=24 and max(abs(a-b) for a,b in zip(frame['color'],other['color']))<=35:
                found.append((distance,other,source))
        return sorted(found,key=lambda m:m[0])[:8]


def film_group(video):
    title=video.get('title','')
    match=re.search(r'John\s+Wick\s*(?::\s*)?(?:Chapter\s*)?([234])\b',title,re.I)
    if match:return 'wick'+match[1]
    if '2014' in title:return 'wick1'
    return None


class Assignment:
    def __init__(self,project):
        require_legacy(project)
        self.project=project;self.folder=project/'media/jev'
        self.cache=pool.cache_dir(project)/'jev-stage4';self.cache.mkdir(exist_ok=True)
        self.hash_cache=self.cache/'hashes';self.hash_cache.mkdir(exist_ok=True)
        self.inputs=json.loads((self.folder/'input-cues.json').read_text(encoding='utf-8'))
        self.cues={c['id']:c for c in self.inputs['cues']}
        self.needs={n['id']:n for n in json.loads((self.folder/'needs.json').read_text(encoding='utf-8'))}
        self.videos={v['id']:v for v in json.loads((self.folder/'download-report.json').read_text(encoding='utf-8'))['videos'] if v['status']=='ready'}
        self.raw=[c for c in json.loads((self.folder/'candidates.json').read_text(encoding='utf-8')) if c['passed'] and c['purpose'] in ['main','miss_audit']]
        self.reference=FrameIndex();self.top_frames=FrameIndex()
        self.pool=collections.defaultdict(list);self.excluded=[];self.used=collections.defaultdict(list);self.used_raw=collections.defaultdict(list)
        self.valid={}
        for key,v in self.videos.items():
            p=pool.cache_dir(project)/'jev-index'/(key+'.black.json')
            black=json.loads(p.read_text())['ranges'] if p.exists() else []
            self.valid[key]=subtract(0,v['probe']['duration'],black)
        self.timing=cue_times(project,list(self.cues.values()))
        self.slots=[];self.share=collections.Counter();self.placements=collections.defaultdict(list)

    def prepare(self):
        references=[v for v in self.videos.values() if film_group(v)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            rows=list(executor.map(lambda v:fingerprints(v,self.hash_cache),references))
        for video,frames in zip(references,rows):
            for frame in frames:self.reference.add(frame,video['id'])
        for raw in self.raw:
            if self.needs[raw['need_id']].get('review_only'):
                continue
            c=dict(raw);v=self.videos[c['video_id']]
            group=self.needs[c['need_id']]['source_group'];actual=film_group(v)
            c.update(canonical_id=c['video_id'],canonical_offset=0.,source_group=actual or group,evidence_need=c['need_id'])
            if group.startswith('wick') and actual is None:
                probes=fingerprints(v,self.hash_cache,c['start'],c['end'])
                hits=collections.defaultdict(list)
                for probe in probes:
                    for distance,frame,vid in self.reference.matches(probe):hits[vid].append((frame['time']-probe['time'],distance,probe['time']))
                best=None
                for vid,matches in hits.items():
                    for offset,_,_ in matches:
                        consistent=[m for m in matches if abs(m[0]-offset)<=.6]
                        if len({m[2] for m in consistent})>=2:
                            rank=(len(consistent),-sum(m[1] for m in consistent)/len(consistent))
                            if best is None or rank>best[0]:best=(rank,vid,sum(m[0] for m in consistent)/len(consistent))
                if best is None:
                    self.excluded.append(dict(id=c['id'],need=c['need_id'],reason='Mixed-film compilation span has no verified film identity'))
                    continue
                _,vid,offset=best
                c.update(canonical_id=vid,canonical_offset=offset,source_group=film_group(self.videos[vid]),film_identity='matched supplied scene frames')
            if actual and actual!=group:
                continue
            # Only trust visibly plausible categories for broader illustrative reuse.
            if c['need_id'] in ['wick2-wrecked-car','wick2-driving-warehouse','wick2-pistol-supply','wick3-roof-fall','wick3-exhausted-zero','wick3-armored-defense','wick4-fire-shotgun']:
                c['exact_rejected']=True
            self.pool[c['need_id']].append(c)
            if c['source_group'].startswith('wick'):
                broad=ROOTS[c['source_group']]
                if not c.get('exact_rejected') or c['need_id'] in ['wick3-armored-defense']:
                    if c not in self.pool[broad]:self.pool[broad].append(c)
        # Visible flame burst in the supplied top-down apartment scene, within a passed action range.
        parent=next((c for c in self.pool['wick4-action'] if c['video_id']=='pksOSHCKp2k' and c['start']<=105 and c['end']>=110),None)
        if parent:
            c=dict(parent,id=parent['id']+'-shotgun',need_id='wick4-fire-shotgun',start=105.,end=110.,
                exact_rejected=False,scene_verified='Visible flame-burst shotgun; supplied Chapter 4 top-down apartment scene')
            self.pool['wick4-fire-shotgun']=[c]
        save_json(self.folder/'assignment-policy.json',dict(action_seconds=MICRO,broad_roots=ROOTS,
            exact_source_allowlist={k:sorted(v) if v is not None else None for k,v in EXACT_SOURCES.items()},
            excluded=self.excluded,non_action_evidence=sorted(NON_ACTION_EVIDENCE),non_fight_sources={k:sorted(v) for k,v in NON_FIGHT_SOURCES.items()},
            scene_recovery=[c for c in self.pool['wick4-fire-shotgun'] if c.get('scene_verified')],
            note='Brief action evidence followed by same-film/game illustrative footage. Exact evidence never falls back. Stage 3 source results remain unchanged.'))

    def candidate_pool(self,key,strict=False):
        rows=self.pool[key]
        if key in ROOTS.values():rows=[c for c in rows if c.get('evidence_need') not in NON_ACTION_EVIDENCE]
        else:rows=[c for c in rows if not c.get('exact_rejected')]
        rows=[c for c in rows if c['canonical_id'] not in NON_FIGHT_SOURCES.get(key,set())]
        if strict:
            allowed=EXACT_SOURCES.get(key)
            rows=[c for c in rows if c.get('scene_verified') or (not c.get('exact_rejected') and (allowed is None or c['canonical_id'] in allowed))]
        return [c for c in rows if c['source_group']==self.needs[key]['source_group']]

    def build_slots(self):
        owner={cue:key for key,n in self.needs.items() for cue in n['cues']}
        action_cue={}
        for key in MICRO.keys() & self.needs.keys():
            cues=[self.cues[k] for k in self.needs[key]['cues']]
            action_cue[key]=min(cues,key=lambda c:(c['match']!='exact',c['line']))['id']
        for cue in sorted(self.cues.values(),key=lambda c:self.timing[c['id']]['start_frame']):
            key=owner[cue['id']];a=self.timing[cue['id']]['start_frame'];b=self.timing[cue['id']]['end_frame']
            if self.needs[key].get('manual'):
                segments=[(a,b,key,True,'manual')]
            elif key in MICRO:
                root=ROOTS[self.needs[key]['source_group']]
                if cue['id']==action_cue[key]:
                    end=min(b,a+round(MICRO[key]*FPS))
                    segments=[(a,end,key,True,'brief action'),(end,b,root,False,'illustrative remainder')]
                else:segments=[(a,b,root,False,'illustrative remainder')]
            else:
                segments=[(a,b,key,cue['match']=='exact','primary')]
            for start,end,need,strict,kind in segments:
                if end<=start:continue
                count=max(1,math.ceil((end-start)/(4*FPS)))
                for i in range(count):
                    lo=start+(end-start)*i//count;hi=start+(end-start)*(i+1)//count
                    self.slots.append(dict(id=f"{cue['id']}-{len(self.slots)}",cue_id=cue['id'],requested_need=key,need_id=need,
                        strict=strict,kind=kind,start_frame=lo,duration_frames=hi-lo,line=cue['line'],quote=cue['quote'],
                        vo_path=self.timing[cue['id']]['vo_path'],top=None,alternates=[]))

    def choices(self,slot,alternate=False):
        key=slot['need_id'];chain=[key]
        if not slot['strict']:
            root=ROOTS[self.needs[key]['source_group']]
            fallback=self.needs[key]['fallback']
            if fallback and fallback not in chain:chain.append(fallback)
            if root not in chain:chain.append(root)
        duration=slot['duration_frames']/FPS
        found=[]
        for rank,need in enumerate(chain):
            for c in self.candidate_pool(need,slot['strict']):
                vid=c['canonical_id'];offset=c['canonical_offset']
                occupied=self.used[vid]+[[a+offset,b+offset] for a,b in self.used_raw[c['video_id']]]
                for lo,hi in subtract(c['start']+offset,c['end']+offset,occupied):
                    if hi-lo+1e-6<duration:continue
                    for va,vb in self.valid[c['video_id']]:
                        start=max(lo-offset,va+HANDLE if va>0 else 0)
                        end=min(hi-offset,vb-HANDLE if vb<self.videos[c['video_id']]['probe']['duration'] else vb)
                        if end-start+1e-6<duration:continue
                        is_spaced=all(abs(t-slot['start_frame'])>=60*FPS for t in self.placements[vid])
                        group=self.needs[need]['source_group'];share=self.share[(group,vid)]
                        total=sum(count for (g,v),count in self.share.items() if g==group)
                        over_share=max(0,share+1-(total+1)*.25)
                        same_alt=alternate and slot['top'] and c['video_id']==slot['top']['video_id']
                        found.append((rank,int(not is_spaced)+2*int(bool(same_alt)),over_share,-c['score'],c,start,need))
        return sorted(found,key=lambda row:row[:4])

    def allocate(self):
        order=sorted(self.slots,key=lambda s:(not s['strict'],
            sum(c['end']-c['start'] for c in self.candidate_pool(s['need_id'],s['strict']))/max(.01,sum(self.cues[k]['seconds_estimate'] for k in self.needs[s['need_id']]['cues'])),s['start_frame']))
        duplicate_rejections=0
        for slot in order:
            for rank,spacing,share,negative,c,a,need in self.choices(slot):
                duration=slot['duration_frames']/FPS
                hashes=fingerprints(self.videos[c['video_id']],self.hash_cache,a,a+duration)
                collisions=collections.defaultdict(set)
                for i,h in enumerate(hashes):
                    for distance,other,source in self.top_frames.matches(h,exclude=c['canonical_id']):collisions[source].add(i)
                if any(len(n)>=2 for n in collisions.values()):
                    duplicate_rejections+=1
                    continue
                top=dict(candidate_id=c['id'],video_id=c['video_id'],start=a,end=a+duration,score=c['score'],
                    canonical_id=c['canonical_id'],canonical_start=a+c['canonical_offset'],canonical_end=a+c['canonical_offset']+duration,
                    need_id=need,evidence_need=c['evidence_need'],fallback=need!=slot['requested_need'],spacing_relaxed=spacing,
                    scene_verified=c.get('scene_verified'))
                slot['top']=top
                self.used[c['canonical_id']].append([top['canonical_start'],top['canonical_end']])
                self.used_raw[c['video_id']].append([a,a+duration])
                self.placements[c['canonical_id']].append(slot['start_frame'])
                self.share[(c['source_group'],c['canonical_id'])]+=1
                for h in hashes:self.top_frames.add(h,c['canonical_id'])
                break
        # Alternates never consume top-track source ranges, and prefer other sources.
        for slot in self.slots:
            if not slot['top']:continue
            for rank,spacing,share,negative,c,a,need in self.choices(slot,alternate=True):
                d=slot['duration_frames']/FPS
                if c['video_id']==slot['top']['video_id'] and not (a+d<=slot['top']['start'] or a>=slot['top']['end']):continue
                if any(x['video_id']==c['video_id'] and not (a+d<=x['start'] or a>=x['end']) for x in slot['alternates']):continue
                slot['alternates'].append(dict(candidate_id=c['id'],video_id=c['video_id'],start=a,end=a+d,score=c['score'],need_id=need))
                if len(slot['alternates'])==2:break
        assert_no_overlap(self.slots)
        result=dict(fps=FPS,handles_seconds=HANDLE,slots=self.slots,duplicate_candidates_rejected=duplicate_rejections,
            original_project=self.inputs['source_project'],original_script_sha256=self.inputs['script_sha256'])
        save_json(self.folder/'assignment.json',result)
        return result


def assert_no_overlap(slots):
    used=collections.defaultdict(list)
    for slot in slots:
        c=slot.get('top')
        if not c:continue
        for kind,key,a,b in [('raw',c['video_id'],c['start'],c['end']),
            ('canonical',c.get('canonical_id',c['video_id']),c.get('canonical_start',c['start']),c.get('canonical_end',c['end']))]:
            if any(a<hi-1e-6 and b>lo+1e-6 for lo,hi in used[(kind,key)]):
                raise AssertionError('Repeated source footage on top track: '+key)
            used[(kind,key)].append([a,b])


def merge_masters(assignments,videos):
    grouped=collections.defaultdict(list)
    for slot in assignments['slots']:
        for c in ([slot['top']] if slot['top'] else [])+slot['alternates']:
            v=videos[c['video_id']]
            grouped[c['video_id']].append([max(0,c['start']-HANDLE),min(v['probe']['duration'],c['end']+HANDLE)])
    masters=[]
    for vid,spans in grouped.items():
        merged=[]
        for a,b in sorted(spans):
            if merged and a<=merged[-1][1]+2 and max(b,merged[-1][1])-merged[-1][0]<=120:
                merged[-1][1]=max(b,merged[-1][1])
            elif not merged or [a,b]!=merged[-1]:merged.append([a,b])
        for a,b in merged:
            masters.append(dict(video_id=vid,start=a,end=b,crop=videos[vid].get('crop'),proxy_size=[videos[vid]['probe']['width'],videos[vid]['probe']['height']],
                file=f'B-roll/jev/{vid}_{a:.3f}-{b:.3f}.mp4'))
    return masters


def cut_masters(project,assignments,videos):
    masters=merge_masters(assignments,videos)
    def cut(master):
        path=project/master['file'];path.parent.mkdir(parents=True,exist_ok=True)
        crop=master['crop'];filters=(f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}," if crop else '')+'scale=-2:480,setsar=1'
        if not path.exists():
            command(['ffmpeg','-v','error','-y','-ss',str(master['start']),'-t',str(master['end']-master['start']),
                '-i',videos[master['video_id']]['path'],'-an','-vf',filters,'-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',str(path)],300)
        master['probe']=qc.probe(path)
        return master
    with ThreadPoolExecutor(max_workers=4) as executor:masters=list(executor.map(cut,masters))
    for slot in assignments['slots']:
        for c in ([slot['top']] if slot['top'] else [])+slot['alternates']:
            master=next(m for m in masters if m['video_id']==c['video_id'] and m['start']<=c['start']+1e-6 and m['end']>=c['end']-1e-6)
            c.update(file=master['file'],source_in=c['start']-master['start'],leading_handle=c['start']-master['start'],trailing_handle=master['end']-c['end'])
    save_json(project/'media/jev/masters.json',masters)
    save_json(project/'media/jev/assignment.json',assignments)
    return masters


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--cut',action='store_true')
    args=parser.parse_args()
    project=args.project.resolve()
    assignment=Assignment(project)
    if project==Path(assignment.inputs['source_project']).resolve():raise ValueError('Original project is read-only')
    assignment.prepare();assignment.build_slots();result=assignment.allocate()
    if args.cut:cut_masters(project,result,assignment.videos)
    print(json.dumps(dict(slots=len(result['slots']),filled=sum(bool(s['top']) for s in result['slots']),alternates=sum(len(s['alternates']) for s in result['slots']))))
