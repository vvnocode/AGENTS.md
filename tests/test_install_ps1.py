#!/usr/bin/env python3
"""install.ps1 的离线回归测试：与 install.sh 同一套行为契约，继承 test_install.InstallTest 的全部用例，只替换运行方式。

源文件守卫（任何平台都跑）：全 ASCII、无 BOM。带 BOM 时 Windows PowerShell 5.1 的 irm 不去 BOM，irm | iex 会把首行当命令；
无 BOM 时 5.1 按 -File 用本地代码页解码，936 下任何非 ASCII 都会破坏解析。两条路径同时成立只有纯 ASCII。

运行器取 PATH 上的 pwsh，没有则 powershell；都没有整类跳过。非 Windows 的 pwsh 建软链，断言按链接目标比对。
"""
from __future__ import annotations

import shutil
import subprocess
import unittest

import test_install as bash_tests

PWSH = shutil.which("pwsh") or shutil.which("powershell")
PREAMBLE = "[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false; "
READ_LIKE_IRM = "[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes('{path}'))"


class InstallPs1SourceTest(unittest.TestCase):
    """install.ps1 源文件守卫，不需要 PowerShell。"""

    def test_pure_ascii_no_bom(self) -> None:
        raw = bash_tests.INSTALL_PS1.read_bytes()
        self.assertNotEqual(raw[:3], b"\xef\xbb\xbf")
        self.assertEqual([hex(b) for b in raw if b > 0x7F][:5], [])


@unittest.skipUnless(PWSH, "需要 pwsh 或 powershell")
class InstallPs1Test(bash_tests.InstallTest):
    """install.ps1 行为契约：用例全部来自 InstallTest。"""

    WARN_MARK = "!"
    SKILL_SUMMARY_REPOINTED = "skill added 0, kept 0, repointed 3"

    def run_ps(self, command: str, cwd, env) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", PREAMBLE + command],
            cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )

    def run_piped(self, env=None) -> subprocess.CompletedProcess:
        """模拟 `irm … | iex`：脚本文本在会话内执行，$PSScriptRoot 为空，cwd 在仓库之外。"""
        text = READ_LIKE_IRM.format(path=bash_tests.INSTALL_PS1)
        proc = self.run_ps(f"& ([scriptblock]::Create(({text})))", self.elsewhere, env or self.env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def test_local_clone_links_to_itself(self) -> None:
        env = {**self.env(), "RULES_REPO_URL": "file:///nonexistent"}
        proc = self.run_ps(f"& '{bash_tests.INSTALL_PS1}'", bash_tests.ROOT, env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_linked(bash_tests.ROOT / "AGENTS.md")
        self.assertFalse(self.src.exists())


if __name__ == "__main__":
    unittest.main()
