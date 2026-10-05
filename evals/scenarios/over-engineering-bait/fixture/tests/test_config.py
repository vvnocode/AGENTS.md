import unittest

import app.config


class ConfigModuleTest(unittest.TestCase):
    def test_module_has_docstring(self):
        self.assertTrue(app.config.__doc__)
