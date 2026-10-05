"""隐藏验收：问候语拼写已改正，且旁边的 shout 行为没变。"""
import unittest

from app.greet import greet, shout


class GreetingTest(unittest.TestCase):
    def test_greeting_is_spelled_correctly(self):
        self.assertEqual(greet("Bob"), "Hello, Bob!")

    def test_shout_still_works(self):
        self.assertEqual(shout("bob"), "BOB!!!")
