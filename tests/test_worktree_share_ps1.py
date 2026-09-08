#!/usr/bin/env python3
"""worktree-share.ps1 的离线回归测试：继承 test_worktree_share 的全部用例，只替换运行器（pwsh 或 powershell）与输出标记。

另加 Windows 专属用例：无符号链接特权时退回目录联接、联接被判为「已就位」、git worktree remove 只删链接不伤根工作区。
源文件另有纯 ASCII 守卫。
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

import test_install_ps1 as install_ps1
import test_worktree_share as bash_tests

SHARE_PS1 = bash_tests.SKILL / "worktree-share.ps1"


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

    def summary(self, new: int, kept: int, warn: int) -> str:
        return f"+ new {new}, kept {kept}, warnings {warn}"

    def run_share(self, path: Path, expect_ok: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SHARE_PS1), "link", str(path)],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace", env=self.env(), check=False,
        )
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def assert_link_to(self, path: Path, target: Path) -> None:
        """符号链接或目录联接都算；目标归一后相等。"""
        if os.path.islink(path):
            self.assertEqual(os.path.normcase(os.readlink(path)), os.path.normcase(str(target)))
            return
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command",
             f"$i = Get-Item -LiteralPath '{path}' -Force; if (-not $i.LinkType) {{ exit 3 }}; Write-Output ([string](@($i.Target)[0]))"],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(proc.returncode, 0, f"{path} 应为链接或联接：{proc.stdout}{proc.stderr}")
        got = proc.stdout.strip()
        if got.startswith("\\\\?\\"):
            got = got[4:]
        self.assertEqual(os.path.normcase(got.rstrip("\\/")), os.path.normcase(str(target)))

    @unittest.skip("钩子在非 Windows 上分派到 .sh，已由基类覆盖")
    def test_git_worktree_add_triggers_sharing(self) -> None:
        pass

    # ── Windows 专属 ──
    def force_no_symlink_privilege(self) -> dict[str, str]:
        """让脚本走联接分支：设 WORKTREE_SHARE_NO_SYMLINK=1（脚本只在测试目的下识别此变量）。"""
        return {**self.env(), "WORKTREE_SHARE_NO_SYMLINK": "1"}

    @unittest.skipUnless(os.name == "nt", "目录联接只有 Windows 有")
    def test_junction_fallback_without_privilege(self) -> None:
        """无符号链接特权：.memory 成为目录联接，指向根工作区。"""
        self.make_standard_fixture()
        wt = self.add_worktree("w1")
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SHARE_PS1), "link", str(wt)],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace",
            env=self.force_no_symlink_privilege(), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        link_type = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-Command", f"(Get-Item -LiteralPath '{wt / '.memory'}' -Force).LinkType"],
            capture_output=True, encoding="utf-8", check=False,
        ).stdout.strip()
        self.assertEqual(link_type, "Junction")
        self.assert_link_to(wt / ".memory", self.root / ".memory")
        self.assertEqual(self.status(wt), "")

    @unittest.skipUnless(os.name == "nt", "目录联接只有 Windows 有")
    def test_junction_counts_as_kept(self) -> None:
        """联接建好后二次执行：全部计 kept。"""
        self.make_standard_fixture()
        wt = self.add_worktree("w2")
        env = self.force_no_symlink_privilege()
        for _ in range(2):
            proc = subprocess.run(
                [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SHARE_PS1), "link", str(wt)],
                cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace", env=env, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(self.summary(0, 4, 0), proc.stdout)

    @unittest.skipUnless(os.name == "nt", "目录联接只有 Windows 有")
    def test_worktree_remove_keeps_root_memory(self) -> None:
        """git worktree remove 只删联接本身，根工作区 .memory 内容完好。"""
        self.make_standard_fixture()
        wt = self.add_worktree("w3")
        proc = subprocess.run(
            [install_ps1.PWSH, "-NoProfile", "-NonInteractive", "-File", str(SHARE_PS1), "link", str(wt)],
            cwd=self.temp_dir.name, capture_output=True, encoding="utf-8", errors="replace",
            env=self.force_no_symlink_privilege(), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.git("worktree", "remove", "--force", str(wt))
        self.assertFalse(wt.exists())
        self.assertEqual((self.root / ".memory" / "MEMORY.md").read_text(encoding="utf-8"), "# 索引\n")
        self.assertTrue((self.root / ".claude" / "skills" / "demo" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
