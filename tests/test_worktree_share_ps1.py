#!/usr/bin/env python3
"""worktree-share.ps1 的离线回归测试：继承 test_worktree_share 的全部用例，只替换运行器（pwsh 或 powershell）与输出标记。

另加：无符号链接特权时目录项不共享只告警（任何有 PowerShell 的平台都跑）；Windows 专属三例：跑过 setup.ps1 后
git worktree add 由钩子分派到 .ps1 自动共享、已存在的目录联接只告警不接受、git worktree remove 只删符号链接不伤根工作区。
联接不作兜底：git（2.37.3 实测）把联接当普通目录，worktree remove 会穿过它删掉根工作区的内容。源文件另有纯 ASCII 守卫。
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

import test_install_ps1 as install_ps1
import test_worktree_share as bash_tests

SHARE_PS1 = bash_tests.SKILL / "worktree-share.ps1"
SETUP_PS1 = bash_tests.SKILL / "setup.ps1"


class SharePs1SourceTest(unittest.TestCase):
    """worktree-share.ps1 源文件守卫，不需要 PowerShell。"""

    def test_pure_ascii_no_bom(self) -> None:
        raw = SHARE_PS1.read_bytes()
        self.assertNotEqual(raw[:3], b"\xef\xbb\xbf")
        self.assertEqual([hex(b) for b in raw if b > 0x7F][:5], [])


@unittest.skipUnless(install_ps1.PWSH, "需要 pwsh 或 powershell")
class SharePs1Test(bash_tests.WorktreeShareTest):
    """worktree-share.ps1 行为契约：用例全部来自 WorktreeShareTest。"""

    COPIED = "* copied"
    LINKED = "* linked"
    WARN_MARK = "!"
    PENDING = "pending commit"
    MAIN_NOOP = "main worktree"
    USES_BASH = False   # 跑 .ps1，Windows 上不跳过

    def summary(self, new: int, kept: int, warn: int) -> str:
        return f"+ new {new}, kept {kept}, warnings {warn}"

    def run_share(self, path: Path, expect_ok: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SHARE_PS1), "link", str(path)],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace", env=env or self.env(), check=False,
        )
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def run_setup_on_root(self) -> subprocess.CompletedProcess:
        """跑 setup.ps1 接线根工作区（装钩子）；运行方式同 test_agent_memory_setup_ps1。"""
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command", install_ps1.PREAMBLE + f"& '{SETUP_PS1}' '{self.root}'"],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace", env=self.env(), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def link_type(self, path: Path) -> str:
        """PowerShell 眼中的链接类型：SymbolicLink / Junction，不是链接为空串。"""
        return subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command", f"(Get-Item -LiteralPath '{path}' -Force).LinkType"],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        ).stdout.strip()

    def assert_link_to(self, path: Path, target: Path) -> None:
        """必须是符号链接（联接不接受），目标归一后相等；Windows 的 readlink 带 \\\\?\\ 前缀，去掉再比。"""
        self.assertTrue(os.path.islink(path), f"{path} 应为符号链接")
        got = os.readlink(path)
        if got.startswith("\\\\?\\"):
            got = got[4:]
        self.assertEqual(os.path.normcase(got.rstrip("\\/")), os.path.normcase(str(target)))

    def no_symlink_privilege(self) -> dict[str, str]:
        """模拟没有建符号链接的特权：设 WORKTREE_SHARE_NO_SYMLINK=1（脚本只在测试目的下识别此变量）。"""
        return {**self.env(), "WORKTREE_SHARE_NO_SYMLINK": "1"}

    def test_no_symlink_privilege_skips_directories(self) -> None:
        """无特权：文件照常复制；目录项链不成时退回到目录自己的文件逐个复制（.codex/config.toml 仍到位）、子目录不共享，
        每个目录一条告警并提示开开发者模式；不退回联接，worktree 内 status 为空。"""
        self.make_standard_fixture()
        wt = self.add_worktree("nopriv")
        proc = self.run_share(wt, env=self.no_symlink_privilege())
        self.assertEqual((wt / "AGENTS.md").read_text(encoding="utf-8"), "# 规则 XYZZY\n")
        self.assertEqual((wt / ".codex" / "config.toml").read_text(encoding="utf-8"), "[memories]\n")
        self.assertFalse((wt / ".codex").is_symlink(), ".codex 链不成，应是真实目录里放副本")
        for rel in (".memory", ".claude/skills"):
            self.assertFalse(os.path.lexists(wt / rel), f"{rel} 不应以任何形式出现在 worktree 里")
        self.assertIn("Developer Mode", proc.stdout)
        self.assertIn(self.summary(2, 0, 3), proc.stdout)     # 告警：.memory、.claude/skills、.codex 各一条
        self.assertEqual(self.status(wt), "")

    # ── Windows 专属 ──
    @unittest.skipUnless(os.name == "nt", "钩子在非 Windows 上分派到 .sh，已由基类覆盖")
    def test_git_worktree_add_triggers_sharing(self) -> None:
        """Windows：setup.ps1 装的钩子由 Git 自带的 sh 执行，按 $OSTYPE 分派到 worktree-share.ps1。"""
        super().test_git_worktree_add_triggers_sharing()

    @unittest.skipUnless(os.name == "nt", "目录联接只有 Windows 有")
    def test_existing_junction_is_warned(self) -> None:
        """worktree 里已有指向根工作区 .memory 的目录联接：不算已就位、不动它，告警提示换成符号链接。"""
        self.make_standard_fixture()
        wt = self.add_worktree("junc")
        subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command",
             f"New-Item -ItemType Junction -Path '{wt / '.memory'}' -Value '{self.root / '.memory'}' | Out-Null"],
            capture_output=True, check=True,
        )
        proc = self.run_share(wt)
        self.assertEqual(self.link_type(wt / ".memory"), "Junction", "脚本不应动用户自建的联接")
        self.assertIn("junction", proc.stdout)
        self.assertIn(self.summary(3, 0, 1), proc.stdout)

    @unittest.skipUnless(os.name == "nt", "验证 Git for Windows 对符号链接的 worktree remove 行为")
    def test_worktree_remove_keeps_root_memory(self) -> None:
        """目录项是符号链接时 git worktree remove 只删链接本身，根工作区 .memory 与 skills 内容完好。"""
        self.make_standard_fixture()
        wt = self.add_worktree("w3")
        self.run_share(wt)
        self.assertEqual(self.link_type(wt / ".memory"), "SymbolicLink")
        self.git("worktree", "remove", "--force", str(wt))
        self.assertFalse(wt.exists())
        self.assertEqual((self.root / ".memory" / "MEMORY.md").read_text(encoding="utf-8"), "# 索引\n")
        self.assertTrue((self.root / ".claude" / "skills" / "demo" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
