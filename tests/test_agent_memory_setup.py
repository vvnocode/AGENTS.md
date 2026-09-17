#!/usr/bin/env python3
"""agent-memory-setup/setup.sh 的离线回归测试：在临时 git 仓库里跑真实脚本，不触碰用户主目录与真实项目。

覆盖：
- 全新仓库一跑到位：CLAUDE.md 只含一行 @AGENTS.md 引用、.memory/MEMORY.md、.claude/settings.local.json 指向仓内 .memory、
  .gitignore 忽略 settings.local.json、.codex/config.toml 不再关 Codex 记忆（由 memory-sync 同步回 .memory）；默认不往 AGENTS.md 写记忆节（全局规则承担）
- 旧接线写的 [memories] 三 false 块被整块删除；用户自定义 [memories] 保留并告警；全局 features.memories 未开只提示不代开
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

    # 本类跑 bash 版脚本；Windows 用 setup.ps1，.sh 不是 Windows 的支持路径，整类跳过。.ps1 子类覆盖为 False
    USES_BASH = True

    def setUp(self) -> None:
        """空的临时 git 仓库。"""
        if self.USES_BASH and os.name == "nt":
            self.skipTest("Windows 走 .ps1，.sh 套件不在支持范围")
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

        toml = (self.repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("[memories]", toml, "Codex 记忆不再关闭")
        self.assertIn("memory-sync", toml)

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

    # ── 第 5 步：Codex 记忆不再关闭 ──
    LEGACY_BLOCK = subprocess.run(
        ["git", "-C", str(ROOT), "show", "51ef95d:skills/agent-memory-setup/setup.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.split("CODEX_BLOCK='")[1].split("'\n")[0] + "\n"    # 2026-09-09 版接线写进 .codex/config.toml 的原文

    def test_legacy_disable_block_is_removed(self) -> None:
        """旧接线写的三 false 块：整块删除，其他内容不动，重跑幂等。"""
        cfg = self.repo / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text("# 用户自己的注释\nfoo = 1\n\n" + self.LEGACY_BLOCK, encoding="utf-8")
        self.run_setup()
        self.assertEqual(cfg.read_text(encoding="utf-8").strip(), "# 用户自己的注释\nfoo = 1")
        before = cfg.read_bytes()
        self.run_setup()
        self.assertEqual(before, cfg.read_bytes())

    LEGACY_VARIANT = (   # 2026-09-08 之前 skills 仓版本写的措辞（本机规则仓自身接线时留下的实物）
        "# 本项目的记忆统一存放在仓库内 .memory/，写入规则见全局规则仓 AGENTS.md 的「项目记忆」节。\n"
        "# Codex 的记忆目录不可配置（固定 $CODEX_HOME/memories），只能把它自带的记忆系统整体关掉。\n"
        "[memories]\ngenerate_memories = false\nuse_memories = false\ndedicated_tools = false\n"
    )

    def test_legacy_variant_block_is_removed_by_structure(self) -> None:
        """措辞不同的旧关闭块：[memories] 节只含三项 false、前面的注释提到 .memory/ 即视为接线产物，整块删除。"""
        cfg = self.repo / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text("foo = 1\n\n" + self.LEGACY_VARIANT + "\n[other]\nbar = 2\n", encoding="utf-8")
        proc = self.run_setup()
        self.assertEqual(cfg.read_text(encoding="utf-8"), "foo = 1\n\n[other]\nbar = 2\n")
        self.assertNotIn(self.WARN_SUMMARY, proc.stdout)

    def test_legacy_only_file_is_removed(self) -> None:
        """文件只含旧块：删文件，重跑再建的是不关记忆的注释文件。"""
        cfg = self.repo / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(self.LEGACY_BLOCK, encoding="utf-8")
        self.run_setup()
        self.assertNotIn("[memories]", cfg.read_text(encoding="utf-8"))

    def test_custom_memories_section_is_kept_with_warning(self) -> None:
        cfg = self.repo / ".codex" / "config.toml"
        cfg.parent.mkdir()
        custom = "[memories]\ngenerate_memories = false\n"
        cfg.write_text(custom, encoding="utf-8")
        proc = self.run_setup()
        self.assertEqual(cfg.read_text(encoding="utf-8"), custom)
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn("[memories]", proc.stdout)
        self.assertIn(self.WARN_SUMMARY, proc.stdout)

    def test_features_off_is_hinted_not_enabled(self) -> None:
        """全局 ~/.codex/config.toml 没开 memories：收尾提示，不改全局文件。"""
        global_cfg = Path(self.temp_dir.name) / ".codex" / "config.toml"
        global_cfg.parent.mkdir(exist_ok=True)
        global_cfg.write_text('model = "x"\n', encoding="utf-8")
        proc = self.run_setup()
        self.assertIn("memories = true", proc.stdout)
        self.assertEqual(global_cfg.read_text(encoding="utf-8"), 'model = "x"\n')

    # ── 第 8 步：worktree 共享钩子 ──
    HOOK_MARK = "# agent-memory-setup post-checkout"

    def hook_path(self) -> Path:
        return self.repo / ".git" / "hooks" / "post-checkout"

    def skill_dir_in_hook(self) -> str:
        """钩子里 SKILL_DIR 的写法；setup.ps1 用正斜杠，子类覆盖。"""
        return str(SETUP.parent)

    def test_hook_is_installed(self) -> None:
        """全新仓跑完：钩子存在、可执行、第 2 行是标记、内含 skill 目录绝对路径。"""
        self.run_setup()
        hook = self.hook_path()
        self.assertTrue(hook.is_file(), "应写入 .git/hooks/post-checkout")
        self.assertTrue(os.access(hook, os.X_OK) or os.name == "nt")
        text = hook.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[1], self.HOOK_MARK)
        self.assertIn(self.skill_dir_in_hook(), text)
        self.assertNotIn("__SKILL_DIR__", text)
        self.assertNotIn("\r\n", text, "钩子由 sh 执行，必须是 LF")

    def test_hook_prefers_global_skill_root(self) -> None:
        """本机 ~/.agents/skills/agent-memory-setup 存在：钩子写这个稳定路径，而不是脚本所在目录（脚本可能在临时 worktree 里）。"""
        global_root = Path(self.temp_dir.name) / ".agents" / "skills"
        global_root.mkdir(parents=True)
        try:
            os.symlink(SETUP.parent, global_root / "agent-memory-setup", target_is_directory=True)
        except OSError as exc:      # Windows 无符号链接特权
            self.skipTest(f"建不了目录符号链接：{exc}")
        self.run_setup()
        text = self.hook_path().read_text(encoding="utf-8").replace("\\", "/")
        expected = (Path(self.temp_dir.name) / ".agents" / "skills" / "agent-memory-setup").as_posix()
        self.assertIn(f'SKILL_DIR="{expected}"', text)

    def test_hook_rerun_unchanged(self) -> None:
        """重跑后钩子字节不变。"""
        self.run_setup()
        before = self.hook_path().read_bytes()
        self.run_setup()
        self.assertEqual(before, self.hook_path().read_bytes())

    def test_hooks_path_set_is_left_alone(self) -> None:
        """仓库已设 core.hooksPath：不写 .git/hooks，告警并给接入指引。"""
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=self.repo, check=True)
        proc = self.run_setup()
        self.assertFalse(self.hook_path().exists())
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn("core.hooksPath", proc.stdout)
        self.assertIn("worktree-share", proc.stdout)

    def test_foreign_hook_is_kept(self) -> None:
        """已有别人的 post-checkout：内容不变，告警并给接入指引。"""
        mine = "#!/bin/sh\necho mine\n"
        self.hook_path().parent.mkdir(parents=True, exist_ok=True)
        self.hook_path().write_text(mine, encoding="utf-8")
        self.hook_path().chmod(0o755)
        proc = self.run_setup()
        self.assertEqual(self.hook_path().read_text(encoding="utf-8"), mine)
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertIn("worktree-share", proc.stdout)

    def test_dangling_hook_symlink_is_not_written_through(self) -> None:
        """钩子位置是悬空软链（旧版 llm-wiki bootstrap 链到的 scripts/hooks/post-checkout 已被删除）：
        不经软链写入——写入会跟随软链在工作区建出未跟踪的钩子文件——软链原样保留，告警。"""
        target = self.repo / "scripts" / "hooks" / "post-checkout"
        target.parent.mkdir(parents=True)
        self.hook_path().parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink("../../scripts/hooks/post-checkout", self.hook_path())
        except OSError as exc:      # Windows 无符号链接特权
            self.skipTest(f"建不了文件符号链接：{exc}")
        proc = self.run_setup()
        self.assertTrue(self.hook_path().is_symlink(), "软链本身不应被替换")
        self.assertFalse(target.exists(), "不得穿过悬空软链在工作区建出钩子文件")
        # 只断言「有告警」区分不开：环境缺 python 等也会告警，所以要求告警行点名钩子
        warnings = [line for line in proc.stdout.splitlines() if line.startswith(self.WARN_MARK)]
        self.assertTrue(any("post-checkout" in line for line in warnings), proc.stdout)

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
