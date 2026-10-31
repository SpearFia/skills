# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import tempfile
import unittest
from pathlib import Path

from jev import expand_sources, parse_checklist, paste_targets, render_checklist, validate_needs, write_checklist


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
            needs = [dict(id="tanks", label="Tanks", query="A tank drives down a road.", variants=[], confirm=dict(question="What is visible?",right="A tank.",wrong=["A car.","A helicopter."]),generic=True,fallback=None,source_scope="Test game",source_group="gta5",cues=["cue"])]
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

    def test_group_questions_and_box_preservation(self):
        fixture = Path(__file__).parent/"examples"/"cwi-003"
        needs = json.loads((fixture/"needs.json").read_text(encoding="utf-8"))
        inputs = json.loads((fixture/"input-cues.json").read_text(encoding="utf-8"))
        sources = {key: [] for key in paste_targets(needs)}
        group_url, other_url = "https://youtu.be/AbCdEf12345", "https://youtu.be/ZyXwVu98765"
        sources["group-wick1"] = [group_url]
        sources["group-gta6"] = [other_url]
        sources["wick1-police-visit"] = [group_url, other_url]
        expanded = expand_sources(needs, sources)
        for need in needs:
            if need.get("manual") or need.get("review_only"):
                self.assertEqual(expanded[need["id"]], [])
            elif need["source_group"] == "wick1":
                self.assertIn(group_url, expanded[need["id"]])
            elif need["source_group"] == "gta6":
                self.assertEqual(expanded[need["id"]], [other_url])
            else:
                self.assertEqual(expanded[need["id"]], [])
        self.assertEqual(expanded["wick1-police-visit"], [group_url, other_url])
        rendered = render_checklist(needs, inputs, sources)
        self.assertLess(rendered.index("## group-gtavc:"), rendered.index("## Optional individual needs"))
        self.assertEqual(parse_checklist(rendered, paste_targets(needs)), sources)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/"media"/"jev"
            folder.mkdir(parents=True)
            for name in ["needs.json", "input-cues.json"]:
                (folder/name).write_bytes((fixture/name).read_bytes())
            (folder/"sources.json").write_text(json.dumps(sources), encoding="utf-8")
            path, _, _ = write_checklist(root)
            write_checklist(root)
            self.assertEqual(parse_checklist(path.read_text(encoding="utf-8"), paste_targets(needs)), sources)
            # Removing a group URL must not preserve it as copied individual entries.
            path.write_text(path.read_text(encoding="utf-8").replace(group_url, "", 1), encoding="utf-8")
            write_checklist(root)
            stored = json.loads((folder/"sources.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["group-wick1"], [])
            self.assertEqual(expand_sources(needs, stored)["wick1-action"], [])
            self.assertEqual(expand_sources(needs, stored)["wick1-police-visit"], [group_url, other_url])
            path.unlink()
            write_checklist(root)
            self.assertEqual(parse_checklist(path.read_text(encoding="utf-8"), paste_targets(needs)), stored)

    def test_strict_exact_fallbacks_and_optional_manual_controls(self):
        fixture = Path(__file__).parent/"examples"/"cwi-003"
        needs = json.loads((fixture/"needs.json").read_text(encoding="utf-8"))
        inputs = json.loads((fixture/"input-cues.json").read_text(encoding="utf-8"))
        cues = validate_needs(needs, inputs)
        by_id = {n["id"]: n for n in needs}
        self.assertEqual(len(needs), 50)
        self.assertEqual(len(cues), 198)
        self.assertEqual(sum(c["match"] == "exact" for c in cues.values()), 21)
        for need in needs:
            if any(cues[key]["match"] == "exact" for key in need["cues"]):
                self.assertIsNone(need["fallback"])
            elif need["cues"] and not need["generic"]:
                self.assertEqual(by_id[need["fallback"]]["source_group"], need["source_group"])
                self.assertTrue(by_id[need["fallback"]]["generic"])
        self.assertTrue(by_id["gta6-six-slot-hud"]["manual"])
        self.assertEqual(by_id["grieving-man"]["source_group"], "wick1")
        url = "https://youtu.be/AbCdEf12345"
        self.assertEqual(expand_sources(needs, {"grieving-man": [url]})["grieving-man"], [url])
        for sources in [{"grieving-man": [url, "https://youtu.be/ZyXwVu98765"]}, {"gta6-six-slot-hud": [url]}]:
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                expand_sources(needs, sources)
        by_id["wick1-police-visit"]["fallback"] = "wick3-action"
        with self.assertRaisesRegex(ValueError, "same film/game"):
            validate_needs(needs, inputs)


if __name__ == "__main__":
    unittest.main()
