# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from jev import parse_checklist, validate_needs, write_checklist


class ChecklistTest(unittest.TestCase):
    def test_tolerant_urls_and_cross_need_reuse(self):
        text = '''# Checklist
## tanks: Tanks
- https://www.youtube.com/watch?v=AbCdEf12345&t=20s
[another](https://youtu.be/ZyXwVu98765).
https://www.youtube.com/watch?v=AbCdEf12345&t=20s
## helicopter: Helicopter
<https://youtu.be/ZyXwVu98765>
'''
        result = parse_checklist(text, ["tanks", "helicopter"])
        self.assertEqual(result["tanks"], ["https://www.youtube.com/watch?v=AbCdEf12345&t=20s", "https://youtu.be/ZyXwVu98765"])
        self.assertEqual(result["helicopter"], ["https://youtu.be/ZyXwVu98765"])

    def test_rejects_unassigned_or_non_video_urls(self):
        for text in ["https://youtu.be/AbCdEf12345", "## tanks: Tanks\nhttps://example.com/video", "## tanks: Tanks\nhttps://youtube.com/playlist?list=abc"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_checklist(text, ["tanks"])

    def test_rewrite_preserves_urls_and_rejects_bad_mapping_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/"media"/"jev"
            folder.mkdir(parents=True)
            inputs = dict(source_project=str(root/"original"), cues=[dict(id="cue", match="subject", visual="", subject="game", quote="A tank arrives.", seconds_estimate=2)])
            needs = [dict(id="tanks", label="Tanks", query="A tank drives down a road.", variants=[], confirm=dict(question="What is visible?",right="A tank.",wrong=["A car.","A helicopter."]),generic=False,fallback=None,source_scope="Test game",cues=["cue"])]
            (folder/"input-cues.json").write_text(json.dumps(inputs))
            (folder/"needs.json").write_text(json.dumps(needs))
            path, _, _ = write_checklist(root)
            path.write_text(path.read_text(encoding="utf-8")+"\n- https://youtu.be/AbCdEf12345\n",encoding="utf-8")
            write_checklist(root)
            self.assertEqual(parse_checklist(path.read_text(encoding="utf-8"), ["tanks"])["tanks"],["https://youtu.be/AbCdEf12345"])
            self.assertEqual(json.loads((folder/"sources.json").read_text(encoding="utf-8"))["tanks"],["https://youtu.be/AbCdEf12345"])
            saved = path.read_bytes()
            needs[0]["cues"] = []
            (folder/"needs.json").write_text(json.dumps(needs))
            with self.assertRaises(ValueError):
                write_checklist(root)
            self.assertEqual(path.read_bytes(),saved)
            needs[0]["cues"] = ["cue"]
            inputs["source_project"] = str(root)
            (folder/"needs.json").write_text(json.dumps(needs))
            (folder/"input-cues.json").write_text(json.dumps(inputs))
            with self.assertRaisesRegex(ValueError,"read-only"):
                write_checklist(root)
            self.assertEqual(path.read_bytes(),saved)


if __name__ == "__main__":
    unittest.main()
