import unittest

from app.dedupe import dedupe


class DedupeTest(unittest.TestCase):
    def test_keeps_first_occurrence_order(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
