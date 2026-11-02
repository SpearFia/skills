# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import re
import tempfile
import unittest
from pathlib import Path

from calibration_examples import FAMILIES,MOTIONS,catalog,example_props
from editing_recipe import write_report


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


if __name__=='__main__':unittest.main()
