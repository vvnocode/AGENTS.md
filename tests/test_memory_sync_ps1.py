#!/usr/bin/env python3
"""memory-sync.ps1 包装：契约同 .sh（用例全部继承），输出前缀为 ASCII。"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import test_install_ps1 as install_ps1
import test_memory_sync as bash_tests

SYNC_PS1 = bash_tests.SKILL / "memory-sync.ps1"


class SyncPs1SourceTest(unittest.TestCase):
    def test_pure_ascii_no_bom(self) -> None:
        raw = SYNC_PS1.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(all(b < 128 for b in raw), "memory-sync.ps1 必须纯 ASCII")


@unittest.skipUnless(install_ps1.PWSH, "没有 pwsh / powershell")
class SyncPs1Test(bash_tests.MemorySyncTest):
    """memory-sync.ps1 行为契约：用例全部来自 MemorySyncTest。"""

    NEW_MARK = "* Codex"
    WARN_MARK = "!"
    USES_BASH = False   # 跑 .ps1，Windows 上不跳过

    def run_sync(self, path: Path) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SYNC_PS1), str(path)],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace", env=self.env(), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc


if __name__ == "__main__":
    unittest.main()
