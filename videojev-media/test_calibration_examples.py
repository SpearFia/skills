# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from calibration_examples import FAMILIES,MOTIONS,catalog,example_props,generate
from editing_recipe import digest,file_hash,save_json,write_report


class CalibrationExampleTests(unittest.TestCase):
    def test_all_twelve_choices_have_readable_five_second_references(self):
        with tempfile.TemporaryDirectory() as d:
            entries=catalog(Path(d))
            self.assertEqual(len(entries),14)
            for kind in FAMILIES:
                for motion in MOTIONS:
                    self.assertIn(kind+'-'+motion,entries)
                    p=example_props(kind,motion)
                    self.assertEqual(p['duration']/p['fps'],5)
                    self.assertEqual(p['reveals'],sorted(p['reveals']))
                    self.assertTrue(all(0<=f<p['duration']-18 for f in p['reveals']))
                    if kind=='source-card':
                        self.assertTrue(p['sourceLabel'])
                        self.assertNotIn(p['sourceLabel'],p['labels'])

    def test_calibration_previews_keep_machine_choice_ids_and_contexts(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            p=dict(id='beat-1',narration='Approved narration',options=['keep','source-card-impact','none-of-these'],flags=[],candidates=[],intent=[],evidence=[])
            recipe=dict(windows=[p],edits=[dict(interval=dict(start=0,end=150))],section=dict(start=0,end=150),timebase=dict(num=30,den=1),criteria_sha256='frozen')
            result=dict(decisions={'beat-1':dict(assessment=dict(choice='keep'),context_sha256='unchanged')})
            write_report(folder,recipe,result)
            page=(folder/'calibration.html').read_text(encoding='utf8')
            self.assertIn('<option value="source-card-impact">Source card · impact</option>',page)
            self.assertIn('Watch 5-second example',page)
            self.assertIn('style-example-video',page)
            payload=json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>',page,re.S)[1])
            self.assertEqual(payload['labels'][0]['context_sha256'],'unchanged')
            self.assertNotIn('choice',payload['labels'][0])

    def test_reference_manifest_cannot_point_outside_its_folder(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'style-examples').mkdir()
            (folder/'style-examples/manifest.json').write_text(json.dumps(dict(examples={'source-card-impact':dict(file='../../other.mp4',poster='https://other/image.jpg')})))
            entry=catalog(folder)['source-card-impact']
            self.assertNotIn('file',entry)
            self.assertNotIn('poster',entry)

    def test_short_study_uses_only_three_pop_references_and_reuses_verified_renders(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'study.json').write_text('{}')
            renderer=folder/'renderer';(renderer/'src').mkdir(parents=True)
            (renderer/'package-lock.json').write_text('{}')
            work=folder/'style-examples';(work/'assets').mkdir(parents=True)
            background=work/'assets/background.mp4';background.write_bytes(b'background fixture')
            code={'package-lock.json':file_hash(renderer/'package-lock.json')}
            for kind in FAMILIES:
                identity=digest(dict(props=example_props(kind,'pop'),code=code,background=file_hash(background),render=dict(scale=.5,crf=23)))
                name=kind+'-pop-'+identity[:12];video=work/(name+'.mp4');poster=work/(name+'.jpg')
                video.write_bytes(b'verified video fixture');poster.write_bytes(b'verified poster fixture')
                save_json(work/(name+'.json'),dict(file=video.name,poster=poster.name,sha256=file_hash(video),poster_sha256=file_hash(poster)))
            with patch('editing_recipe.RENDERER',renderer),patch('calibration_examples.subprocess.run') as process:
                records=generate(folder)
                self.assertEqual(set(records),{k+'-pop' for k in FAMILIES});process.assert_not_called()
                self.assertEqual(len(catalog(folder)),5)


if __name__=='__main__':unittest.main()
