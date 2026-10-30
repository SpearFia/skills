# SPDX-License-Identifier: MIT OR Apache-2.0
import unittest

from benchmark import estimate


class EstimateTest(unittest.TestCase):
    def test_shared_encoding_once_per_window(self):
        case = dict(duration_seconds=1800, prepare_seconds=1,
                    encode_median_seconds=2, batch40_seconds=40)
        self.assertEqual(estimate(case, 10800, 10), 10 + 6 * (1 + 2 + 40))


if __name__ == "__main__":
    unittest.main()
