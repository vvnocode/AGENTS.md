import unittest

from app.greet import shout


class ShoutTest(unittest.TestCase):
    def test_shout(self):
        self.assertEqual(shout("bob"), "BOB!!!")
