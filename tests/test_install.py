#!/usr/bin/env python3
"""install.sh 的离线回归测试：HOME 与托管仓目录都指向临时目录，远端用本地 file:// 仓库代替 GitHub，不联网、不触碰用户主目录。

覆盖：
- 管道运行（curl | bash）：脚本不在磁盘上、cwd 在仓库之外，自行 clone 到 RULES_REPO_DIR，再把五个用户级入口软链到 AGENTS.md
- 重跑：托管副本 git pull 拿到新规则，软链原样不动、读到新内容
- 在本仓 clone 内直接运行：不 clone、不建托管副本，软链直接指向本仓
- 入口已是普通文件：只告警不覆盖（用户须手动合并）
- 入口已是指向别处的链接：只告警不覆盖
- 未传 RULES_REPO_DIR：托管副本落在 ~/.vvnocode/rules；旧默认位置（XDG_CONFIG_HOME 下的 vibe-coding-rules）已有副本时搬过去，指向旧位置的链接重指
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
INSTALL_PS1 = ROOT / "install.ps1"
# 五个用户级规则入口，相对 HOME（XDG_CONFIG_HOME 与 DSH_HOME 在测试环境里固定指到 HOME 下）
ENTRIES = (".claude/CLAUDE.md", ".codex/AGENTS.md", ".gemini/GEMINI.md", ".config/opencode/AGENTS.md", ".dsh/AGENTS.md")
# 三处全局 Skill 发现根，相对 HOME；agent-memory-setup 软链到每一处
SKILL_ROOTS = (".agents/skills", ".claude/skills", ".codex/skills")
GIT_CONFIG = ["-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "core.autocrlf=false"]


def link_target(path: Path) -> str | None:
    """软链目标；不是链接返回 None。"""
    try:
        target = os.readlink(path)
    except OSError:
        return None
    return target[4:] if target.startswith("\\\\?\\") else target


class InstallTest(unittest.TestCase):
    """install.sh 行为契约。"""

    WARN_MARK = "⚠"
    LEGACY_ENV = "XDG_CONFIG_HOME"   # 旧默认托管位置的父目录（install.ps1 同名，Windows 上 README 旧写法是 ~/.config）
    # 本类跑 bash 版脚本；Windows 用 install.ps1，.sh 不是 Windows 的支持路径，整类跳过。.ps1 子类覆盖为 False
    USES_BASH = True

    def setUp(self) -> None:
        if self.USES_BASH and os.name == "nt":
            self.skipTest("Windows 走 .ps1，.sh 套件不在支持范围")
        self.temp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self.temp_dir.name).resolve()
        self.home = tmp / "home"
        self.origin = tmp / "origin"
        self.src = tmp / "src"
        self.elsewhere = tmp / "elsewhere"
        self.home.mkdir()
        self.elsewhere.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ── 构造远端 ──
    def make_origin(self, rules: str = "# rules v1\n") -> None:
        """建一个形如本仓的远端：install.sh、install.ps1、AGENTS.md，提交到 main。"""
        self.origin.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.origin, check=True)
        for script in (INSTALL, INSTALL_PS1):
            shutil.copy(script, self.origin / script.name)
        (self.origin / "AGENTS.md").write_text(rules, encoding="utf-8")
        # 远端也带 skill 目录：install 要把它软链到三处发现根
        skill = self.origin / "skills" / "agent-memory-setup"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: agent-memory-setup\n---\n", encoding="utf-8")
        self.commit("init")

    def commit(self, msg: str) -> None:
        subprocess.run(["git", *GIT_CONFIG, "add", "-A"], cwd=self.origin, check=True)
        subprocess.run(["git", *GIT_CONFIG, "commit", "-q", "-m", msg], cwd=self.origin, check=True)

    # ── 运行 ──
    def env(self) -> dict[str, str]:
        env = {
            **os.environ,
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "DSH_HOME": str(self.home / ".dsh"),
            "RULES_REPO_URL": self.origin.as_uri(),
            "RULES_REPO_DIR": str(self.src),
        }
        if os.name != "nt":
            env["LC_ALL"] = "en_US.UTF-8"
        return env

    def env_without_repo_dir(self) -> dict[str, str]:
        """不指定 RULES_REPO_DIR，让脚本用默认位置。"""
        env = self.env()
        env.pop("RULES_REPO_DIR")
        return env

    def run_piped(self, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        """模拟 `curl ... | bash`：脚本从 stdin 进入，cwd 在仓库之外。"""
        proc = subprocess.run(
            ["bash", "-s", "--"], input=INSTALL.read_text(encoding="utf-8"),
            cwd=self.elsewhere, env=env or self.env(), capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def entry(self, rel: str) -> Path:
        return self.home / rel

    def assert_linked(self, target: Path, entries=ENTRIES) -> None:
        for rel in entries:
            link = self.entry(rel)
            actual = link_target(link)
            self.assertIsNotNone(actual, f"{link} 应为链接")
            self.assertEqual(os.path.normcase(actual), os.path.normcase(str(target)), rel)

    # ── 全局钩子 ──
    def claude_settings(self) -> Path:
        return self.home / ".claude" / "settings.json"

    def codex_hooks(self) -> Path:
        return self.home / ".codex" / "hooks.json"

    def hook_commands(self, path: Path, event: str) -> list[str]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [h["command"] for grp in data["hooks"][event] for h in grp["hooks"]]

    def test_piped_installs_two_global_hooks(self) -> None:
        """全局安装写 Claude SessionStart 与 Codex SessionStart 各一条 memory-sync 钩子，并打印改了哪两个文件。"""
        self.make_origin()
        proc = self.run_piped()
        claude = self.hook_commands(self.claude_settings(), "SessionStart")
        codex = self.hook_commands(self.codex_hooks(), "SessionStart")
        self.assertEqual(len([c for c in claude if "agent-memory-setup" in c and "memory-sync" in c]), 1, claude)
        self.assertEqual(len([c for c in codex if "agent-memory-setup" in c and "memory-sync" in c]), 1, codex)
        self.assertIn("settings.json", proc.stdout)
        self.assertIn("hooks.json", proc.stdout)

    def test_hooks_are_merged_not_overwritten_and_idempotent(self) -> None:
        self.make_origin()
        self.claude_settings().parent.mkdir(parents=True)
        self.claude_settings().write_text(json.dumps({
            "theme": "dark",
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
        }), encoding="utf-8")
        self.run_piped()
        data = json.loads(self.claude_settings().read_text(encoding="utf-8"))
        self.assertEqual(data["theme"], "dark")
        self.assertIn("echo mine", self.hook_commands(self.claude_settings(), "SessionStart"))
        before = (self.claude_settings().read_bytes(), self.codex_hooks().read_bytes())
        self.run_piped()
        self.assertEqual(before, (self.claude_settings().read_bytes(), self.codex_hooks().read_bytes()))

    def test_rules_no_hooks_skips(self) -> None:
        self.make_origin()
        self.write_codex_config("[features]\ncodex_hooks = true\n")
        self.run_piped({**self.env(), "RULES_NO_HOOKS": "1"})
        self.assertFalse(self.claude_settings().exists())
        self.assertFalse(self.codex_hooks().exists())
        self.assertEqual(self.codex_config().read_text(encoding="utf-8"), "[features]\ncodex_hooks = true\n", "开关迁移随钩子一起跳过")

    # ── Codex 钩子开关：hooks 默认开启，codex_hooks 是弃用别名 ──
    def codex_config(self) -> Path:
        return self.home / ".codex" / "config.toml"

    def write_codex_config(self, text: str) -> None:
        self.codex_config().parent.mkdir(parents=True, exist_ok=True)
        self.codex_config().write_text(text, encoding="utf-8")

    def test_codex_deprecated_codex_hooks_key_is_renamed(self) -> None:
        """Codex 0.147 起 [features].codex_hooks 是弃用别名（启动打 deprecated 警告），正名 hooks：只改这一行、保留原值，其余字节不动，重跑幂等。"""
        self.make_origin()
        self.write_codex_config('model = "x"\n\n[features]\ncodex_hooks = true\njs_repl = false\n\n[other]\nk = 1\n')
        proc = self.run_piped()
        self.assertEqual(self.codex_config().read_text(encoding="utf-8"),
                         'model = "x"\n\n[features]\nhooks = true\njs_repl = false\n\n[other]\nk = 1\n')
        self.assertIn("codex_hooks", proc.stdout)
        before = self.codex_config().read_bytes()
        proc = self.run_piped()
        self.assertEqual(before, self.codex_config().read_bytes())
        self.assertNotIn(self.WARN_MARK, proc.stdout, proc.stdout)

    def test_codex_hooks_false_is_kept_with_warning(self) -> None:
        """用户明确关了 hooks（弃用名写 false 同样保留 false）：不改值，只告警 memory-sync 钩子不会跑。"""
        self.make_origin()
        self.write_codex_config("[features]\ncodex_hooks = false\n")
        proc = self.run_piped()
        self.assertEqual(self.codex_config().read_text(encoding="utf-8"), "[features]\nhooks = false\n")
        self.assertIn(self.WARN_MARK, proc.stdout, proc.stdout)
        self.write_codex_config("[features]\nhooks = false\n")
        proc = self.run_piped()
        self.assertEqual(self.codex_config().read_text(encoding="utf-8"), "[features]\nhooks = false\n")
        self.assertIn(self.WARN_MARK, proc.stdout, proc.stdout)

    def test_codex_config_without_features_is_untouched(self) -> None:
        """钩子默认开启：没有 config.toml 不创建，没有 [features] 节不补写；codex_hooks 出现在别的节里也不动。"""
        self.make_origin()
        self.run_piped()
        self.assertFalse(self.codex_config().exists())
        self.write_codex_config('[projects."/x"]\ntrust_level = "trusted"\ncodex_hooks = true\n')
        before = self.codex_config().read_bytes()
        proc = self.run_piped()
        self.assertEqual(before, self.codex_config().read_bytes())
        self.assertNotIn(self.WARN_MARK, proc.stdout, proc.stdout)

    def test_invalid_json_is_left_alone_with_warning(self) -> None:
        self.make_origin()
        self.claude_settings().parent.mkdir(parents=True)
        self.claude_settings().write_text("{not json", encoding="utf-8")
        proc = self.run_piped()
        self.assertEqual(self.claude_settings().read_text(encoding="utf-8"), "{not json")
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assertTrue(self.codex_hooks().exists(), "另一处不受影响")

    # ── 用例 ──
    def test_piped_clones_and_links(self) -> None:
        self.make_origin()
        self.run_piped()
        self.assertTrue((self.src / ".git").is_dir(), "应在 RULES_REPO_DIR 建托管副本")
        self.assert_linked(self.src / "AGENTS.md")
        self.assertEqual(self.entry(".claude/CLAUDE.md").read_text(encoding="utf-8"), "# rules v1\n")
        self.assertEqual(list(self.elsewhere.iterdir()), [])

    def test_rerun_pulls_update(self) -> None:
        self.make_origin()
        self.run_piped()
        (self.origin / "AGENTS.md").write_text("# rules v2\n", encoding="utf-8")
        self.commit("v2")
        self.run_piped()
        self.assert_linked(self.src / "AGENTS.md")
        self.assertEqual(self.entry(".codex/AGENTS.md").read_text(encoding="utf-8"), "# rules v2\n")

    def test_local_clone_links_to_itself(self) -> None:
        env = {**self.env(), "RULES_REPO_URL": "file:///nonexistent"}   # 若尝试 clone 必失败
        proc = subprocess.run(["bash", str(INSTALL)], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_linked(ROOT / "AGENTS.md")
        self.assertFalse(self.src.exists())

    def test_existing_plain_file_is_kept(self) -> None:
        self.make_origin()
        mine = self.entry(".claude/CLAUDE.md")
        mine.parent.mkdir(parents=True)
        mine.write_text("mine\n", encoding="utf-8")
        proc = self.run_piped()
        self.assertFalse(mine.is_symlink())
        self.assertEqual(mine.read_text(encoding="utf-8"), "mine\n")
        self.assertIn(self.WARN_MARK, proc.stdout)
        self.assert_linked(self.src / "AGENTS.md", entries=tuple(e for e in ENTRIES if e != ".claude/CLAUDE.md"))

    def test_existing_foreign_link_is_kept(self) -> None:
        self.make_origin()
        other = self.home / "other.md"
        other.write_text("other\n", encoding="utf-8")
        link = self.entry(".gemini/GEMINI.md")
        link.parent.mkdir(parents=True)
        link.symlink_to(other)
        proc = self.run_piped()
        self.assertEqual(os.path.normcase(link_target(link)), os.path.normcase(str(other)))
        self.assertIn(self.WARN_MARK, proc.stdout)

    def test_default_dir_is_under_vvnocode(self) -> None:
        self.make_origin()
        self.run_piped(self.env_without_repo_dir())
        new_dir = self.home / ".vvnocode" / "rules"
        self.assertTrue((new_dir / ".git").is_dir(), "默认托管位置应为 ~/.vvnocode/rules")
        self.assert_linked(new_dir / "AGENTS.md")

    def test_legacy_dir_is_moved_and_links_repointed(self) -> None:
        self.make_origin()
        legacy = self.home / ".config" / "vibe-coding-rules"
        legacy.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", self.origin.as_uri(), str(legacy)], check=True, capture_output=True)
        link = self.entry(".claude/CLAUDE.md")
        link.parent.mkdir(parents=True)
        link.symlink_to(legacy / "AGENTS.md")
        proc = self.run_piped(self.env_without_repo_dir())
        new_dir = self.home / ".vvnocode" / "rules"
        self.assertTrue((new_dir / ".git").is_dir(), proc.stdout)
        self.assertFalse(legacy.exists(), "旧托管目录应已搬走")
        self.assert_linked(new_dir / "AGENTS.md")
        self.assertNotIn(self.WARN_MARK, proc.stdout, proc.stdout)

    def test_link_to_old_file_name_is_repointed(self) -> None:
        """入口指向本仓旧文件名 CLAUDE.md（2026-09-08 改名前的安装）：重指到 AGENTS.md，不告警。"""
        self.make_origin()
        link = self.entry(".codex/AGENTS.md")
        link.parent.mkdir(parents=True)
        link.symlink_to(self.src / "CLAUDE.md")
        proc = self.run_piped()
        self.assert_linked(self.src / "AGENTS.md")
        self.assertNotIn(self.WARN_MARK, proc.stdout, proc.stdout)

    # ── skill 软链到三处 Skill 发现根 ──
    SKILL_SUMMARY_REPOINTED = "skill 新建 0 条，已就位 0 条，重指 3 条"   # install.ps1 全 ASCII，子类覆盖

    def skill_link(self, root: str) -> Path:
        return self.home / root / "agent-memory-setup"

    def assert_skill_linked(self, target: Path) -> None:
        for root in SKILL_ROOTS:
            actual = link_target(self.skill_link(root))
            self.assertIsNotNone(actual, f"{root} 下应有 agent-memory-setup 链接")
            self.assertEqual(os.path.normcase(actual), os.path.normcase(str(target)), root)

    def test_piped_links_skill_to_three_roots(self) -> None:
        """管道运行后三处发现根都有 agent-memory-setup 软链，指向托管副本内的 skill 目录。"""
        self.make_origin()
        self.run_piped()
        self.assert_skill_linked(self.src / "skills" / "agent-memory-setup")

    def test_skill_link_to_old_skills_repo_is_repointed(self) -> None:
        """发现根里指向旧 skills 仓托管位置的链接：重指到本仓，不告警。"""
        self.make_origin()
        old = self.home / ".vvnocode" / "skills" / "skills" / "agent-memory-setup"
        old.mkdir(parents=True)
        for root in SKILL_ROOTS:
            self.skill_link(root).parent.mkdir(parents=True, exist_ok=True)
            self.skill_link(root).symlink_to(old)
        proc = self.run_piped()
        self.assert_skill_linked(self.src / "skills" / "agent-memory-setup")
        self.assertIn(self.SKILL_SUMMARY_REPOINTED, proc.stdout)
        self.assertNotIn(self.WARN_MARK, proc.stdout, proc.stdout)

    def test_skill_root_plain_dir_is_kept(self) -> None:
        """发现根里已是普通目录：不覆盖，告警，其余两处照装。"""
        self.make_origin()
        mine = self.skill_link(".claude/skills")
        mine.mkdir(parents=True)
        (mine / "keep").write_text("x", encoding="utf-8")
        proc = self.run_piped()
        self.assertFalse(mine.is_symlink())
        self.assertTrue((mine / "keep").is_file())
        self.assertIn(self.WARN_MARK, proc.stdout)
        for root in (".agents/skills", ".codex/skills"):
            self.assertEqual(os.path.normcase(link_target(self.skill_link(root))), os.path.normcase(str(self.src / "skills" / "agent-memory-setup")))


if __name__ == "__main__":
    unittest.main()
