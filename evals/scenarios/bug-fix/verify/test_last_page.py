"""隐藏验收：不足一页的最后一页能翻到。"""
import unittest

from app.paginate import paginate


class LastPageTest(unittest.TestCase):
    def test_last_partial_page_is_reachable(self):
        self.assertEqual(paginate(list(range(1, 11)), 4, 3), [10])

    def test_page_beyond_the_end_is_still_empty(self):
        self.assertEqual(paginate(list(range(1, 11)), 5, 3), [])
