#!/usr/bin/env python3
"""agent-memory-setup/setup.ps1 的离线回归测试：继承 test_agent_memory_setup 的全部用例，只替换运行器（pwsh 或 powershell.exe）。

另加 Windows 专属用例：从 macOS/Linux 提交的 CLAUDE.md 软链在 Windows（core.symlinks=false）检出后是只含 AGENTS.md 的文本文件、
索引里仍是 120000，setup.ps1 要把它改为引用行并重新按普通文件暂存。源文件另有纯 ASCII 守卫。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

import test_agent_memory_setup as bash_tests
import test_install_ps1 as install_ps1

SETUP_PS1 = bash_tests.SETUP.parent / "setup.ps1"


class SetupPs1SourceTest(unittest.TestCase):
    """setup.ps1 源文件守卫，不需要 PowerShell。"""

    def test_pure_ascii_no_bom(self) -> None:
        """全 ASCII 且无 BOM，原因同 install.ps1。"""
        raw = SETUP_PS1.read_bytes()
        self.assertNotEqual(raw[:3], b"\xef\xbb\xbf")
        self.assertEqual([hex(b) for b in raw if b > 0x7F][:5], [])


@unittest.skipUnless(install_ps1.PWSH, "需要 pwsh 或 powershell")
class SetupPs1Test(bash_tests.AgentMemorySetupTest):
    """setup.ps1 行为契约：用例全部来自 AgentMemorySetupTest。"""

    WARN_MARK = "!"
    HELP_TEXT = "Usage"
    WARN_SUMMARY = "1 warning(s)"

    def trust_snippet(self) -> str:
        return '[projects."' + str(self.repo).replace("\\", "\\\\") + '"]'

    def run_ps(self, command: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": self.temp_dir.name, "USERPROFILE": self.temp_dir.name}
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command", install_ps1.PREAMBLE + command],
            cwd=cwd or self.repo, env=env, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def run_setup(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """按文件路径运行：$PSScriptRoot 指向 skill 目录。"""
        quoted = " ".join(f"'{a}'" for a in args)
        return self.run_ps(f"& '{SETUP_PS1}' {quoted}", cwd=cwd)

    def run_piped(self, *args: str) -> subprocess.CompletedProcess:
        """模拟 irm | iex：脚本文本在会话内执行，$PSScriptRoot 为空。"""
        quoted = " ".join(f"'{a}'" for a in args)
        text = install_ps1.READ_LIKE_IRM.format(path=SETUP_PS1)
        return self.run_ps(f"& ([scriptblock]::Create(({text}))) {quoted}")

    def test_legacy_symlink_is_migrated(self) -> None:
        """真实软链（需要权限）：有权限就跑父类用例，没有就跳过，检出文本的情形由下一个用例覆盖。"""
        try:
            (self.repo / "probe.lnk").symlink_to("AGENTS.md")
        except OSError as exc:
            self.skipTest(f"本机无权建文件软链：{exc}")
        (self.repo / "probe.lnk").unlink()
        super().test_legacy_symlink_is_migrated()

    @unittest.skipUnless(os.name == "nt", "只有 Windows 会把软链检出成文本文件")
    def test_checked_out_symlink_text_is_migrated(self) -> None:
        """索引里 120000、工作区里是只含 AGENTS.md 的文本文件：改为引用行，并按普通文件重新暂存。"""
        (self.repo / "AGENTS.md").write_text("# 规则\n\n口令 PLOVER\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("AGENTS.md", encoding="utf-8")
        blob = subprocess.run(["git", "hash-object", "-w", "CLAUDE.md"], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"120000,{blob},CLAUDE.md"], cwd=self.repo, check=True)
        self.run_setup()
        self.assert_import_line()
        entry = subprocess.run(["git", "ls-files", "-s", "CLAUDE.md"], cwd=self.repo, capture_output=True, text=True, check=True).stdout
        self.assertTrue(entry.startswith("100644 "), entry)
        self.assertIn("PLOVER", (self.repo / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
