"""隐藏验收：根因在 page_count 的向下取整；只在 paginate 里打补丁过不了这一条。"""
import unittest

from app.paginate import page_count


class PageCountTest(unittest.TestCase):
    def test_page_count_rounds_up(self):
        self.assertEqual(page_count(10, 3), 4)
        self.assertEqual(page_count(9, 3), 3)
        self.assertEqual(page_count(1, 3), 1)
        self.assertEqual(page_count(0, 3), 0)
