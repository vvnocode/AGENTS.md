#!/usr/bin/env python3
"""agent-memory-setup/setup.sh 的离线回归测试：在临时 git 仓库里跑真实脚本，不触碰用户主目录与真实项目。

覆盖：
- 全新仓库一跑到位：CLAUDE.md 只含一行 @AGENTS.md 引用、.memory/MEMORY.md、.claude/settings.local.json 指向仓内 .memory、
  .gitignore 忽略 settings.local.json、.codex/config.toml 三项记忆开关全关；默认不往 AGENTS.md 写记忆节（全局规则承担）
- 重跑幂等：第二次运行后所有产物字节不变
- 只有 CLAUDE.md 的仓库：改名为 AGENTS.md 并写引用行，正文不丢
- 旧做法留下的 CLAUDE.md -> AGENTS.md 软链：自动改为引用行（普通文件）
- AGENTS.md 与 CLAUDE.md 都是普通文件且内容不同：不动任何一个，只告警，其余步骤照做
- --with-rule：才往 AGENTS.md 追加「项目记忆」节，且重跑不重复追加
- 管道运行（curl | bash）：--help 不依赖磁盘上的脚本文件；收尾的 Codex 探针提示给出 curl 命令
- 在仓库之外传仓库路径运行：产物仍落在该仓库里
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills" / "agent-memory-setup" / "setup.sh"


def sha(path: Path) -> str:
    """文件内容摘要，用于幂等比对；软链按其目标字符串计算。"""
    if path.is_symlink():
        return "link:" + os.readlink(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AgentMemorySetupTest(unittest.TestCase):
    """setup.sh 行为契约。"""

    # 输出里的告警标记与帮助文字；setup.ps1 全 ASCII，子类覆盖
    WARN_MARK = "⚠"
    HELP_TEXT = "用法"
    WARN_SUMMARY = "共 1 条告警"      # 收尾汇总行

    def trust_snippet(self) -> str:
        """收尾输出里的 Codex 信任片段首行；Windows 版把反斜杠按 TOML 转义。"""
        return f'[projects."{self.repo}"]'

    def setUp(self) -> None:
        """空的临时 git 仓库。"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name).resolve() / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_setup(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """在临时仓库里跑 setup.sh，HOME 指向临时目录以防误写用户主目录。cwd 缺省为仓库本身。"""
        env = {**os.environ, "HOME": self.temp_dir.name, "LC_ALL": "en_US.UTF-8"}   # UTF-8：覆盖 bash 3.2 的多字节解析路径
        proc = subprocess.run(
            ["bash", str(SETUP), *args], cwd=cwd or self.repo, capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def snapshot(self) -> dict[str, str]:
        """仓库内全部产物的摘要（排除 .git）。"""
        return {
            str(p.relative_to(self.repo)): sha(p)
            for p in self.repo.rglob("*")
            if ".git" not in p.parts and (p.is_file() or p.is_symlink())
        }

    def test_fresh_repo_gets_everything(self) -> None:
        """全新仓库一次跑齐五项产物。"""
        proc = self.run_setup()
        self.assert_import_line()
        self.assertTrue((self.repo / ".memory" / "MEMORY.md").is_file())

        settings = json.loads((self.repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        self.assertEqual(os.path.normcase(settings["autoMemoryDirectory"]), os.path.normcase(str(self.repo / ".memory")))
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".claude/settings.local.json"], cwd=self.repo, check=False,
        )
        self.assertEqual(ignored.returncode, 0, ".claude/settings.local.json 必须被 gitignore")

        toml = (self.repo / ".codex" / "config.toml").read_text()
        for key in ("generate_memories", "use_memories", "dedicated_tools"):
            self.assertRegex(toml, rf"{key}\s*=\s*false")

        # 默认不写仓内记忆节：读写规则由全局规则仓承担，避免每仓一份重复
        self.assertNotIn("项目记忆", (self.repo / "AGENTS.md").read_text())
        # 收尾必须给出 Codex 信任片段，路径是仓库绝对路径
        self.assertIn(self.trust_snippet(), proc.stdout)

    def test_rerun_is_idempotent(self) -> None:
        """第二次运行不改动任何已就位产物。"""
        self.run_setup()
        before = self.snapshot()
        self.run_setup()
        self.assertEqual(before, self.snapshot())

    def test_only_claude_md_is_renamed(self) -> None:
        """仓库原本只有 CLAUDE.md：正文迁到 AGENTS.md，CLAUDE.md 变引用行。"""
        (self.repo / "CLAUDE.md").write_text("# 原有规则\n\n口令 XYZZY\n")
        self.run_setup()
        self.assert_import_line()
        self.assertIn("XYZZY", (self.repo / "AGENTS.md").read_text())

    def assert_import_line(self) -> None:
        """CLAUDE.md 是普通文件，内容只有一行 @AGENTS.md。"""
        claude = self.repo / "CLAUDE.md"
        self.assertFalse(claude.is_symlink(), "CLAUDE.md 不应再是软链")
        self.assertEqual(claude.read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_explicit_path_from_outside_repo(self) -> None:
        """在仓库之外的目录里传仓库路径运行：所有产物仍落在该仓库里（相对路径不能按进程当前目录解析）。"""
        self.run_setup(str(self.repo), cwd=Path(self.temp_dir.name))
        self.assert_import_line()
        self.assertTrue((self.repo / ".memory" / "MEMORY.md").is_file())
        self.assertTrue((self.repo / ".codex" / "config.toml").is_file())
        self.assertEqual(list(Path(self.temp_dir.name).glob(".memory")), [])

    def test_legacy_symlink_is_migrated(self) -> None:
        """旧做法留下的 CLAUDE.md -> AGENTS.md 软链：改为引用行，AGENTS.md 正文不动。"""
        (self.repo / "AGENTS.md").write_text("# 规则\n\n口令 PLUGH\n")
        (self.repo / "CLAUDE.md").symlink_to("AGENTS.md")
        self.run_setup()
        self.assert_import_line()
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "# 规则\n\n口令 PLUGH\n")

    def test_conflicting_files_are_left_alone(self) -> None:
        """两份普通文件内容不同：不合并、不覆盖，告警后其余步骤照做。"""
        (self.repo / "AGENTS.md").write_text("# A\n")
        (self.repo / "CLAUDE.md").write_text("# C\n")
        proc = self.run_setup()
        self.assertFalse((self.repo / "CLAUDE.md").is_symlink())
        self.assertEqual((self.repo / "CLAUDE.md").read_text(), "# C\n")
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn(self.WARN_SUMMARY, proc.stdout)
        self.assertTrue((self.repo / ".memory" / "MEMORY.md").is_file())

    def test_with_rule_appends_section_once(self) -> None:
        """--with-rule 追加「项目记忆」节，重跑不重复。"""
        (self.repo / "AGENTS.md").write_text("# 规则\n")
        self.run_setup("--with-rule")
        agents = (self.repo / "AGENTS.md").read_text()
        self.assertIn("## 项目记忆", agents)
        self.assertIn("MEMORY.md", agents)
        self.run_setup("--with-rule")
        self.assertEqual(agents, (self.repo / "AGENTS.md").read_text())

    def run_piped(self, *args: str) -> subprocess.CompletedProcess:
        """模拟 `curl ... | bash -s -- 参数`：脚本从 stdin 进入，$0 是 bash，磁盘上没有脚本文件。"""
        env = {**os.environ, "HOME": self.temp_dir.name, "LC_ALL": "en_US.UTF-8"}
        proc = subprocess.run(
            ["bash", "-s", "--", *args], input=SETUP.read_text(encoding="utf-8"),
            cwd=self.repo, capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def test_piped_help_works_without_script_file(self) -> None:
        """curl | bash -s -- --help：脚本不在磁盘上，帮助文本仍能打印。"""
        proc = self.run_piped("--help")
        self.assertIn(self.HELP_TEXT, proc.stdout)
        self.assertIn("--with-rule", proc.stdout)

    def test_probe_hint_matches_how_script_was_run(self) -> None:
        """收尾的 Codex 验证提示：本地有探针就给本地路径，管道运行时给可直接执行的 curl 命令。"""
        local = self.run_setup()
        self.assertIn(str(SETUP.parent / "codex-effective-config.py"), local.stdout)
        piped = self.run_piped()
        self.assertIn(
            "https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/codex-effective-config.py",
            piped.stdout,
        )


if __name__ == "__main__":
    unittest.main()
