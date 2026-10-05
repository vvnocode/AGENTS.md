import os
import tempfile
import unittest

from app.notes import add_note, list_notes


class NotesTest(unittest.TestCase):
    def test_add_then_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "notes.json")
            add_note(path, "first")
            add_note(path, "second")
            self.assertEqual([n["text"] for n in list_notes(path)], ["first", "second"])
