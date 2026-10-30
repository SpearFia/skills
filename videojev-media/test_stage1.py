# SPDX-License-Identifier: MIT OR Apache-2.0
import unittest

from stage1 import run, summarize
from stage1_alignment import selected_frames


class AccuracyReviewTest(unittest.TestCase):
    def test_context_cap_rejects_job_before_loading_model(self):
        with self.assertRaisesRegex(ValueError, "never higher"):
            run({"contexts": [32769]}, {}, lambda: None)

    def test_absent_scores_do_not_become_a_found_span(self):
        result = summarize([0.03, 0.07], [[0,1],[1,2]], 17.25)
        self.assertEqual(result["spans"], [])
        self.assertEqual(result["seconds_ge_050"], 0)
        self.assertEqual(result["max"], 0.07)

    def test_distinct_spans_and_source_offsets(self):
        result = summarize([0.9,0.8,0.1,0.1,0.8,0.9], [[i,i+1] for i in range(6)], 10)
        self.assertEqual([(s["start"],s["end"]) for s in result["spans"]],[(10,12),(14,16)])

    def test_sampler_matches_selected_picture_not_output_timestamp(self):
        log = 'Parsed_showinfo_0 pts_time:2.48 checksum:ABC\nParsed_showinfo_2 pts_time:0 checksum:ABC'
        self.assertEqual(selected_frames(log)[0]["error"],2.48)


if __name__ == "__main__":
    unittest.main()
