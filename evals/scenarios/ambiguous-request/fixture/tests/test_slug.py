import unittest

from app.slug import slugify


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_strips_edges(self):
        self.assertEqual(slugify("  --Already Slugged--  "), "already-slugged")
