import unittest

from app.text import shorten


class ShortenTest(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(shorten("abc", 5), "abc")

    def test_long_text_is_cut(self):
        self.assertEqual(shorten("abcdef", 3), "abc")
