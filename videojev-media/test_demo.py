# SPDX-License-Identifier: MIT OR Apache-2.0
import unittest

from demo import check_ready


class ReadinessTest(unittest.TestCase):
    def test_gpu_floor_and_comfy_jobs(self):
        check_ready({"queue_running": [], "queue_pending": []}, 12288, 12288)
        for queue, free in [({"queue_running": [1], "queue_pending": []}, 14000),
                            ({"queue_running": [], "queue_pending": [1]}, 14000),
                            ({"queue_running": [], "queue_pending": []}, 12287), ({}, 14000)]:
            with self.subTest(queue=queue, free=free), self.assertRaises(RuntimeError):
                check_ready(queue, free, 12288)


if __name__ == "__main__":
    unittest.main()
