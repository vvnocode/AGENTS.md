#!/usr/bin/env python3
"""worktree-share.sh 的离线回归测试：临时 git 仓库里建真实 worktree，跑真实脚本，不触碰用户主目录。

覆盖：
- 根工作区被忽略的项：文件成副本、目录成软链，worktree 内 git status 为空
- .claude/settings.local.json 永不共享（Claude 原生回读主工作区），写进 .worktree-share 也不共享并告警
- 未入库也未忽略的项：视为待提交，不共享，告警
- 已入库的项：跳过、无输出，worktree 检出自带
- 忽略规则带尾斜杠（.memory/）：软链后 .git/info/exclude 补一行 .memory，worktree 内 status 仍为空
- worktree 里已有真实文件：不覆盖，告警
- 对根工作区执行：只提示，退出 0，不产生文件
- 二次执行：全部计「已就位」，无新建
- .worktree-share：追加自定义目录与文件、! 剔除内置项、只在 worktree 分支里新增也生效、前缀含入库文件时展开其下被忽略条目
- 跑过 setup.sh 后 git worktree add：钩子自动共享
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agent-memory-setup"
SHARE = SKILL / "worktree-share.sh"
SETUP = SKILL / "setup.sh"
GIT_CONFIG = ["-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "core.autocrlf=false"]


class WorktreeShareTest(unittest.TestCase):
    """worktree-share.sh 行为契约；.ps1 子类只替换运行器与输出标记。"""

    # 输出标记；worktree-share.ps1 全 ASCII，子类覆盖
    COPIED = "· 已复制"
    LINKED = "· 已链"
    WARN_MARK = "⚠"
    PENDING = "待提交"
    MAIN_NOOP = "根工作区"

    def summary(self, new: int, kept: int, warn: int) -> str:
        return f"✓ 新建 {new}，已就位 {kept}，告警 {warn}"

    def setUp(self) -> None:
        """一个有一次空提交的临时仓库作为根工作区。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "root"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ── 夹具 ──
    def git(self, *args: str, cwd: Path | None = None) -> str:
        proc = subprocess.run(["git", *GIT_CONFIG, *args], cwd=cwd or self.root, capture_output=True, text=True, check=True)
        return proc.stdout

    def write(self, rel: str, text: str, cwd: Path | None = None) -> Path:
        path = (cwd or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit_all(self, cwd: Path | None = None) -> None:
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", "fixture", cwd=cwd)

    def add_worktree(self, name: str) -> Path:
        """在 .worktrees/<name> 建附属 worktree（新分支）。.worktrees/ 须已被忽略。"""
        wt = self.root / ".worktrees" / name
        self.git("worktree", "add", "-q", str(wt), "-b", name)
        return wt

    def status(self, cwd: Path) -> str:
        return self.git("status", "--short", cwd=cwd)

    def env(self) -> dict[str, str]:
        env = {**os.environ, "HOME": self.temp_dir.name, "USERPROFILE": self.temp_dir.name}
        if os.name != "nt":
            env["LC_ALL"] = "en_US.UTF-8"
        return env

    def run_share(self, path: Path, expect_ok: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(SHARE), "link", str(path)], cwd=self.temp_dir.name,
                              capture_output=True, text=True, env=self.env(), check=False)
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def run_setup_on_root(self) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(SETUP), str(self.root)], cwd=self.temp_dir.name,
                              capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def assert_link_to(self, path: Path, target: Path) -> None:
        """path 是指向 target 的目录链接。"""
        self.assertTrue(path.is_symlink(), f"{path} 应为软链")
        self.assertEqual(os.path.normcase(os.readlink(path)), os.path.normcase(str(target)))

    def exclude_file(self) -> Path:
        return self.root / ".git" / "info" / "exclude"

    def make_standard_fixture(self) -> None:
        """四个被忽略的接线项：两个文件、两个目录。"""
        self.write(".gitignore", ".worktrees/\nAGENTS.md\n.codex/\n.memory\n.claude/skills\n")
        self.commit_all()
        self.write("AGENTS.md", "# 规则 XYZZY\n")
        self.write(".codex/config.toml", "[memories]\n")
        self.write(".memory/MEMORY.md", "# 索引\n")
        self.write(".claude/skills/demo/SKILL.md", "---\nname: demo\n---\n")

    # ── 内置清单 ──
    def test_ignored_items_are_shared(self) -> None:
        """文件项成副本、目录项成软链，worktree 内 status 为空。"""
        self.make_standard_fixture()
        wt = self.add_worktree("t1")
        proc = self.run_share(wt)
        self.assertEqual((wt / "AGENTS.md").read_text(encoding="utf-8"), "# 规则 XYZZY\n")
        self.assertFalse((wt / "AGENTS.md").is_symlink())
        self.assertEqual((wt / ".codex" / "config.toml").read_text(encoding="utf-8"), "[memories]\n")
        self.assert_link_to(wt / ".memory", self.root / ".memory")
        self.assert_link_to(wt / ".claude" / "skills", self.root / ".claude" / "skills")
        self.assertEqual(self.status(wt), "")
        self.assertIn(self.COPIED, proc.stdout)
        self.assertIn(self.LINKED, proc.stdout)
        self.assertIn(self.summary(4, 0, 0), proc.stdout)

    def test_settings_local_is_never_shared(self) -> None:
        """根工作区有被忽略的 .claude/settings.local.json：worktree 里不出现。"""
        self.write(".gitignore", ".worktrees/\n.claude/settings.local.json\n")
        self.commit_all()
        self.write(".claude/settings.local.json", '{"autoMemoryDirectory": "x"}\n')
        wt = self.add_worktree("t2")
        self.run_share(wt)
        self.assertFalse((wt / ".claude" / "settings.local.json").exists())

    def test_untracked_unignored_is_warned_not_shared(self) -> None:
        """AGENTS.md 未入库也未忽略：不共享，告警含「待提交」。"""
        self.write(".gitignore", ".worktrees/\n")
        self.commit_all()
        self.write("AGENTS.md", "# 未提交\n")
        wt = self.add_worktree("t3")
        proc = self.run_share(wt)
        self.assertFalse((wt / "AGENTS.md").exists())
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn(self.PENDING, proc.stdout)
        self.assertIn(self.summary(0, 0, 1), proc.stdout)

    def test_tracked_item_is_skipped_silently(self) -> None:
        """AGENTS.md 已入库：脚本不提它，worktree 检出自带。"""
        self.write(".gitignore", ".worktrees/\n")
        self.write("AGENTS.md", "# 入库\n")
        self.commit_all()
        wt = self.add_worktree("t4")
        proc = self.run_share(wt)
        self.assertEqual((wt / "AGENTS.md").read_text(encoding="utf-8"), "# 入库\n")
        self.assertNotIn("AGENTS.md", proc.stdout)
        self.assertIn(self.summary(0, 0, 0), proc.stdout)

    def test_trailing_slash_rule_gets_exclude_line(self) -> None:
        """.gitignore 写 .memory/（尾斜杠，不匹配软链）：脚本往 info/exclude 补一行 .memory，worktree status 为空。"""
        self.write(".gitignore", ".worktrees/\n.memory/\n")
        self.commit_all()
        self.write(".memory/MEMORY.md", "# 索引\n")
        wt = self.add_worktree("t5")
        proc = self.run_share(wt)
        self.assert_link_to(wt / ".memory", self.root / ".memory")
        self.assertIn(".memory", self.exclude_file().read_text(encoding="utf-8").splitlines())
        self.assertEqual(self.status(wt), "")
        self.assertIn(self.summary(1, 0, 0), proc.stdout)

    def test_existing_real_target_is_kept(self) -> None:
        """worktree 里已有内容不同的真实 AGENTS.md：不覆盖，告警。"""
        self.make_standard_fixture()
        wt = self.add_worktree("t6")
        self.write("AGENTS.md", "# worktree 自己的\n", cwd=wt)
        proc = self.run_share(wt)
        self.assertEqual((wt / "AGENTS.md").read_text(encoding="utf-8"), "# worktree 自己的\n")
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn(self.summary(3, 0, 1), proc.stdout)

    def test_main_worktree_is_noop(self) -> None:
        """对根工作区执行：退出 0，提示是根工作区，不产生任何文件。"""
        self.make_standard_fixture()
        before = sorted(p.relative_to(self.root) for p in self.root.rglob("*") if ".git" not in p.parts)
        proc = self.run_share(self.root)
        self.assertIn(self.MAIN_NOOP, proc.stdout)
        after = sorted(p.relative_to(self.root) for p in self.root.rglob("*") if ".git" not in p.parts)
        self.assertEqual(before, after)

    def test_second_run_is_all_kept(self) -> None:
        """二次执行：新建 0，已就位 4。"""
        self.make_standard_fixture()
        wt = self.add_worktree("t7")
        self.run_share(wt)
        proc = self.run_share(wt)
        self.assertIn(self.summary(0, 4, 0), proc.stdout)

    # ── .worktree-share 配置 ──
    def test_conf_adds_custom_dir_and_file(self) -> None:
        """配置追加被忽略的目录 cache 与文件 local.toml：目录软链、文件副本。"""
        self.write(".gitignore", ".worktrees/\ncache/\nlocal.toml\n")
        self.write(".worktree-share", "# 本仓额外共享\ncache/\n./local.toml\n")
        self.commit_all()
        self.write("cache/blob", "b")
        self.write("local.toml", "k = 1\n")
        wt = self.add_worktree("c1")
        proc = self.run_share(wt)
        self.assert_link_to(wt / "cache", self.root / "cache")
        self.assertEqual((wt / "local.toml").read_text(encoding="utf-8"), "k = 1\n")
        self.assertFalse((wt / "local.toml").is_symlink())
        self.assertEqual(self.status(wt), "")
        self.assertIn(self.summary(2, 0, 0), proc.stdout)

    def test_conf_bang_removes_builtin(self) -> None:
        """配置写 !.env：根工作区被忽略的 .env 不出现在 worktree。"""
        self.write(".gitignore", ".worktrees/\n.env\n")
        self.write(".worktree-share", "!.env\n")
        self.commit_all()
        self.write(".env", "SECRET=1\n")
        wt = self.add_worktree("c2")
        proc = self.run_share(wt)
        self.assertFalse((wt / ".env").exists())
        self.assertIn(self.summary(0, 0, 0), proc.stdout)

    def test_conf_only_in_worktree_branch_counts(self) -> None:
        """根工作区没有 .worktree-share，worktree 分支里提交了一份：该项照样共享。"""
        self.write(".gitignore", ".worktrees/\ncache/\n")
        self.commit_all()
        self.write("cache/blob", "b")
        wt = self.add_worktree("c3")
        self.write(".worktree-share", "cache\n", cwd=wt)
        self.commit_all(cwd=wt)
        self.run_share(wt)
        self.assert_link_to(wt / "cache", self.root / "cache")

    def test_tracked_prefix_expands_ignored_children(self) -> None:
        """repos/.gitkeep 入库、repos/a 被忽略：worktree 里 repos 是真实目录，repos/a 是软链，.gitkeep 是检出文件。"""
        self.write(".gitignore", ".worktrees/\nrepos/*\n!repos/.gitkeep\n")
        self.write("repos/.gitkeep", "")
        self.write(".worktree-share", "repos\n")
        self.commit_all()
        self.write("repos/a/file", "x")
        wt = self.add_worktree("c4")
        proc = self.run_share(wt)
        self.assertTrue((wt / "repos").is_dir() and not (wt / "repos").is_symlink())
        self.assertTrue((wt / "repos" / ".gitkeep").is_file())
        self.assert_link_to(wt / "repos" / "a", self.root / "repos" / "a")
        self.assertEqual(self.status(wt), "")
        self.assertIn(self.summary(1, 0, 0), proc.stdout)

    def test_settings_local_in_conf_is_refused(self) -> None:
        """配置里写 .claude/settings.local.json：不共享，告警。"""
        self.write(".gitignore", ".worktrees/\n.claude/settings.local.json\n")
        self.write(".worktree-share", ".claude/settings.local.json\n")
        self.commit_all()
        self.write(".claude/settings.local.json", "{}\n")
        wt = self.add_worktree("c5")
        proc = self.run_share(wt)
        self.assertFalse((wt / ".claude" / "settings.local.json").exists())
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn("settings.local.json", proc.stdout)

    # ── 钩子集成 ──
    def test_git_worktree_add_triggers_sharing(self) -> None:
        """跑 setup.sh 后 git worktree add：钩子自动共享，无需手动调脚本。"""
        self.write(".gitignore", ".worktrees/\n.codex/\n")
        self.commit_all()
        self.run_setup_on_root()                     # 写 .memory、.codex/config.toml、settings.local.json、钩子
        self.commit_all()                            # .memory、AGENTS.md、CLAUDE.md 入库；.codex 与 settings.local.json 被忽略
        wt = self.add_worktree("hook")
        self.assertEqual((wt / ".codex" / "config.toml").read_text(encoding="utf-8"),
                         (self.root / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertFalse((wt / ".claude" / "settings.local.json").exists())
        self.assertEqual(self.status(wt), "")


if __name__ == "__main__":
    unittest.main()
