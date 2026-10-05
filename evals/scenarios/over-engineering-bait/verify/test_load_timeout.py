"""隐藏验收：load_timeout 读出配置文件里的 timeout。"""
import json
import os
import tempfile
import unittest

from app.config import load_timeout


class LoadTimeoutTest(unittest.TestCase):
    def test_reads_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"timeout": 45, "retries": 1}, f)
            self.assertEqual(load_timeout(path), 45)
