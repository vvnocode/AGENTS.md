import unittest

from app.paginate import page_count, paginate


class PaginateTest(unittest.TestCase):
    def test_exact_multiple(self):
        items = list(range(1, 10))
        self.assertEqual(page_count(9, 3), 3)
        self.assertEqual(paginate(items, 3, 3), [7, 8, 9])

    def test_out_of_range_page_is_empty(self):
        self.assertEqual(paginate([1, 2, 3], 5, 3), [])
