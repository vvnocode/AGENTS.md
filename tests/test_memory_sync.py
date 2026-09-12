#!/usr/bin/env python3
"""memory-sync.py 的离线回归测试：伪 CODEX_HOME + 临时 git 仓，跑真实脚本，不触碰用户主目录。

覆盖：
- 只同步 cwd 落在目标仓库（根、附属 worktree、已删 worktree 路径前缀）内的线程；另一仓库的句子一字不出现
- 一个列表项一条文件，frontmatter 与 Claude 自动记忆同形；三个标签映射 feedback / feedback / project；References 丢弃
- 同一句子跨线程只一条；线程有 raw 块就整份不取其会话摘要（复述不进来），没有 raw 块的线程才用摘要；文件名是内容哈希，重排列表项不新增文件
- 索引段：放 MEMORY.md 末尾、用户原行不动、每条一行同形、超 60 行截断并告警；只收 frontmatter 带 source: codex 的文件，手写的同前缀条目不进段
- 幂等：重跑字节不变；新增列表项只多一文件一索引行
- 掩码：含 token 的句子被替换为 [已掩码]
- 无 .memory / 无 CODEX_HOME/memories：退出 0、无输出、不建目录
- 自动提交：.memory 已入库才提交，pathspec 偏提交不带走别人已暂存的改动；未入库 / 合并进行中 / 开关关闭时不提交
- 对附属 worktree 执行：写到主工作区 .memory
- .sh / .ps1 包装透传（.ps1 子类）
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agent-memory-setup"
SYNC_PY = SKILL / "memory-sync.py"
SYNC_SH = SKILL / "memory-sync.sh"
GIT_CONFIG = ["-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "core.autocrlf=false"]

# 仿 Codex 0.147 的 raw_memories.md：三个线程，两个属仓 A（根与 worktree），一个属仓 B
RAW_TEMPLATE = """# Raw Memories

Merged stage-1 raw memories (stable ascending thread-id order):

## Thread `aaaaaaaa-0000-0000-0000-000000000001`
updated_at: 2026-09-01T10:00:00+00:00
cwd: {cwd_a}
rollout_path: /x/rollout-a.jsonl
rollout_summary_file: 2026-09-01T10-00-00-aaaa-a_task.md

---
description: 仓 A 的接线与测试
task: wire repo a
task_group: repo-a-wiring
task_outcome: success
cwd: {cwd_a}
keywords: a, wiring
---

### Task 1: 接线

task: wire
task_group: repo-a-wiring
task_outcome: success

Preference signals:
- 用户说“先不push”，说明默认保持本地，不推送远端。
- 用户要求提交前先跑全量测试。
- 部署令牌 ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 写在 .env 里。

Reusable knowledge:
- 本仓测试命令是 `python3 -m unittest discover -s tests`。

Failures and how to do differently:
- 初次只改 CSS 后真机仍无响应；今后触控修复应同时加入即时反馈。

References:
- docs/handover.md

## Thread `bbbbbbbb-0000-0000-0000-000000000002`
updated_at: 2026-09-02T10:00:00+00:00
cwd: {cwd_a_wt}
rollout_path: /x/rollout-b.jsonl
rollout_summary_file: 2026-09-02T10-00-00-bbbb-b_task.md

---
description: 仓 A 的 worktree 会话
task: wt session
task_group: repo-a-wiring
task_outcome: partial
cwd: {cwd_a_wt}
keywords: a
---

### Task 1: worktree

Preference signals:
- 用户要求提交前先跑全量测试。
- worktree 里 .memory 是软链。

## Thread `cccccccc-0000-0000-0000-000000000003`
updated_at: 2026-09-03T10:00:00+00:00
cwd: {cwd_b}
rollout_path: /x/rollout-c.jsonl
rollout_summary_file: 2026-09-03T10-00-00-cccc-c_task.md

---
description: 仓 B 的会话
task: repo b
task_group: repo-b
task_outcome: success
cwd: {cwd_b}
keywords: b
---

### Task 1: b

Preference signals:
- 仓 B 专属句子 ZZZZ 不应出现在仓 A。
"""

# 仿 rollout_summaries/*.md：与线程 a 同一会话（a 有 raw 块，摘要整份不取）
ROLLOUT_A = """thread_id: aaaaaaaa-0000-0000-0000-000000000001
updated_at: 2026-09-01T10:00:00+00:00
rollout_path: /x/rollout-a.jsonl
cwd: {cwd_a}
git_branch: main

# 仓 A 的接线与测试

Rollout context: `{cwd_a}`，接线仓库。

## Task 1: 接线

Outcome: success

Preference signals:
- 用户说“先不push”，说明默认保持本地，不推送远端。

Preference signals:
- 换个说法的同一事实 PARAPHRASE：测试用 unittest discover 跑。

## Task 2: 信任配置

Outcome: success

Preference signals:
- 摘要独有句子：设置 Codex 信任要写绝对路径。
"""

# 没有 raw 块的线程 d：只有会话摘要，摘要生效，分组名退回 thread 前 8 位
ROLLOUT_D = """thread_id: dddddddd-0000-0000-0000-000000000004
updated_at: 2026-09-04T10:00:00+00:00
rollout_path: /x/rollout-d.jsonl
cwd: {cwd_a}
git_branch: main

# 仓 A 的只有摘要的会话

## Task 1: 摘要线程

Outcome: success

Preference signals:
- 无 raw 块线程的摘要句子 ONLYROLLOUT。
"""


class MemorySyncTest(unittest.TestCase):
    """memory-sync 行为契约；.ps1 子类只换运行器与输出前缀。"""

    NEW_MARK = "· Codex 记忆同步：新增"
    WARN_MARK = "⚠"
    USES_BASH = True

    def setUp(self) -> None:
        """伪 HOME、伪 CODEX_HOME、两个临时仓：A 已接线（有 .memory）、B 没有；A 另有一个附属 worktree。"""
        if self.USES_BASH and os.name == "nt":
            self.skipTest("Windows 走 .ps1，.sh 套件不在支持范围")
        self.temp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self.temp_dir.name).resolve()
        self.home = tmp / "home"
        self.home.mkdir()
        self.codex_home = self.home / ".codex"
        self.repo_a = tmp / "repo-a"
        self.repo_b = tmp / "repo-b"
        for r in (self.repo_a, self.repo_b):
            r.mkdir()
            self.git(r, "init", "-q", "-b", "main")
            self.git(r, "config", "user.name", "test")
            self.git(r, "config", "user.email", "test@example.com")
            (r / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
            self.git(r, "add", "-A")
            self.git(r, "commit", "-q", "-m", "init")
        (self.repo_a / ".memory").mkdir()
        (self.repo_a / ".memory" / "MEMORY.md").write_text("# 记忆索引\n\n- [用户自己的条目](own.md) — 不许动\n", encoding="utf-8")
        self.wt_a = self.repo_a / ".worktrees" / "task1"
        self.git(self.repo_a, "worktree", "add", "-q", str(self.wt_a), "-b", "task1")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ── 夹具 ──
    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *GIT_CONFIG, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout

    def write_codex(self, raw: str = RAW_TEMPLATE, rollouts: dict[str, str] | None = None) -> None:
        """写伪 ~/.codex/memories；模板里的 cwd 占位替换为本次临时仓的真实路径。"""
        mem = self.codex_home / "memories"
        (mem / "rollout_summaries").mkdir(parents=True, exist_ok=True)
        fmt = dict(cwd_a=str(self.repo_a), cwd_a_wt=str(self.wt_a), cwd_b=str(self.repo_b))
        (mem / "raw_memories.md").write_text(raw.format(**fmt), encoding="utf-8")
        files = rollouts if rollouts is not None else {"2026-09-01T10-00-00-aaaa-a_task.md": ROLLOUT_A,
                                                        "2026-09-04T10-00-00-dddd-d_task.md": ROLLOUT_D}
        for name, text in files.items():
            (mem / "rollout_summaries" / name).write_text(text.format(**fmt), encoding="utf-8")

    def env(self) -> dict[str, str]:
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "CODEX_HOME": str(self.codex_home)}
        if os.name != "nt":
            env["LC_ALL"] = "en_US.UTF-8"
        return env

    def run_sync(self, path: Path) -> subprocess.CompletedProcess:
        proc = subprocess.run(["bash", str(SYNC_SH), str(path)], cwd=self.temp_dir.name,
                              capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def codex_files(self) -> list[Path]:
        return sorted((self.repo_a / ".memory").glob("codex-*.md"))

    def index(self) -> str:
        return (self.repo_a / ".memory" / "MEMORY.md").read_text(encoding="utf-8")

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in (self.repo_a / ".memory").iterdir() if p.is_file()}

    def find(self, sub: str) -> tuple[Path, str]:
        """含子串的那条记忆文件与全文；找不到即失败。"""
        for p in self.codex_files():
            text = p.read_text(encoding="utf-8")
            if sub in text:
                return p, text
        self.fail(f"没有包含「{sub}」的条目")

    # ── T1：归属、格式、静默场景 ──
    def test_only_own_cwd_is_synced(self) -> None:
        """仓 A 得到根与 worktree 两线程的句子；仓 B 的句子一字不出现。"""
        self.write_codex()
        proc = self.run_sync(self.repo_a)
        texts = "\n".join(p.read_text(encoding="utf-8") for p in self.codex_files())
        self.assertIn("默认保持本地", texts)
        self.assertIn("worktree 里 .memory 是软链", texts)
        self.assertNotIn("ZZZZ", texts)
        self.assertNotIn("ZZZZ", self.index())
        self.assertIn(self.NEW_MARK, proc.stdout)

    def test_one_bullet_one_file_with_claude_frontmatter(self) -> None:
        """一个列表项一文件；frontmatter 键顺序固定；两个保留标签都映射 feedback；References 丢弃。"""
        self.write_codex()
        self.run_sync(self.repo_a)
        p, text = self.find("默认保持本地")
        self.assertRegex(p.name, r"^codex-[0-9A-Za-z\u4e00-\u9fff-]{1,12}-[0-9a-f]{6}\.md$")
        head = text.split("---\n")[1]
        self.assertRegex(
            head,
            r"^name: codex-[^\n]+-[0-9a-f]{6}\ndescription: .+\nmetadata:\n  type: feedback\n  source: codex\n"
            r"  thread_id: aaaaaaaa-0000-0000-0000-000000000001\n  observed_at: 2026-09-01T10:00:00\+00:00\n$",
        )
        self.assertIn("  type: feedback", self.find("触控修复")[1])
        texts = [f.read_text(encoding="utf-8") for f in self.codex_files()]
        self.assertFalse(any("docs/handover.md" in t for t in texts), "References 应丢弃")
        self.assertTrue(all(t.count("\n---\n") == 1 for t in texts), "正文里不能再出现 --- 分隔")
        self.assertTrue(all("rollout_path" not in t for t in texts))
        self.assertIn("来源：Codex 会话「仓 A 的接线与测试」，2026-09-01。", text)

    def test_file_name_carries_sentence_head(self) -> None:
        """文件名是 codex-<句子开头>-<6 位哈希>：一眼看出内容，不再带 Codex 的 task_group。"""
        self.write_codex()
        self.run_sync(self.repo_a)
        p, text = self.find("默认保持本地")
        self.assertTrue(p.stem.startswith("codex-用户说"), p.name)
        self.assertIn(f"name: {p.stem}\n", text, "frontmatter 的 name 要与文件名一致")
        self.assertFalse([q for q in self.codex_files() if "repo-a-wiring" in q.name], "不该再带 task_group")

    def test_legacy_named_entry_is_renamed_not_duplicated(self) -> None:
        """既有条目按句子认领：命名方案变了就改名，不新建第二份。"""
        self.write_codex()
        self.run_sync(self.repo_a)
        p, text = self.find("默认保持本地")
        legacy = p.parent / "codex-repo-a-wiring-0123456789.md"
        p.rename(legacy)
        legacy.write_text(text.replace(f"name: {p.stem}", "name: codex-repo-a-wiring-0123456789"), encoding="utf-8")
        n_before = len(self.codex_files())
        self.run_sync(self.repo_a)
        self.assertFalse(legacy.exists(), "旧命名文件应被改名")
        self.assertEqual(n_before, len(self.codex_files()), "不该多出一份")
        q, qtext = self.find("默认保持本地")
        self.assertEqual(p.name, q.name)
        self.assertIn(f"name: {q.stem}\n", qtext)
        self.assertNotIn("codex-repo-a-wiring-0123456789", self.index())

    def test_reusable_knowledge_is_not_synced(self) -> None:
        """Reusable knowledge 是事实结论，按分工不进 .memory；跳过条数在有新增时一并报出。"""
        self.write_codex()
        proc = self.run_sync(self.repo_a)
        texts = "\n".join(p.read_text(encoding="utf-8") for p in self.codex_files())
        self.assertNotIn("本仓测试命令是", texts, "事实结论不该落地")
        self.assertNotIn("本仓测试命令是", self.index())
        self.assertIn("默认保持本地", texts, "做事方式照常落地")
        self.assertIn("触控修复", texts)
        self.assertIn("跳过", proc.stdout)

    def test_no_memory_dir_is_silent_noop(self) -> None:
        """仓 B 没有 .memory：退出 0、无输出、不建目录。"""
        self.write_codex()
        proc = self.run_sync(self.repo_b)
        self.assertEqual(proc.stdout, "")
        self.assertFalse((self.repo_b / ".memory").exists())

    def test_missing_codex_home_is_silent_noop(self) -> None:
        proc = self.run_sync(self.repo_a)
        self.assertEqual(proc.stdout + proc.stderr, "")
        self.assertEqual(self.codex_files(), [])

    def test_worktree_target_writes_to_main_worktree(self) -> None:
        """对附属 worktree 执行：文件落在主工作区 .memory。"""
        self.write_codex()
        self.run_sync(self.wt_a)
        self.assertTrue(self.codex_files())
        self.assertFalse((self.wt_a / ".memory").exists())

    # ── T2：去重、幂等、索引、掩码 ──
    def test_duplicate_sentences_collapse_to_one_file(self) -> None:
        """「先不push」在 raw 与摘要都出现、「先跑全量测试」在两个线程都出现：各只一条，来源是首次出现（updated_at 最早）的线程。"""
        self.write_codex()
        self.run_sync(self.repo_a)
        texts = [p.read_text(encoding="utf-8") for p in self.codex_files()]
        self.assertEqual(sum("默认保持本地" in t for t in texts), 1)
        dup = [t for t in texts if "先跑全量测试" in t]
        self.assertEqual(len(dup), 1)
        self.assertIn("thread_id: aaaaaaaa-", dup[0])
        # 线程 a 有 raw 块：它的会话摘要整份不取（含换说法的复述与摘要独有句子）
        self.assertEqual(sum("摘要独有句子" in t for t in texts), 0)
        self.assertEqual(sum("PARAPHRASE" in t for t in texts), 0)
        # 线程 d 没有 raw 块：摘要生效，分组名退回 thread 前 8 位
        self.assertRegex(self.find("ONLYROLLOUT")[0].name, r"^codex-.+-[0-9a-f]{6}\.md$")

    def test_rerun_is_byte_identical_and_reorder_adds_nothing(self) -> None:
        self.write_codex()
        self.run_sync(self.repo_a)
        before = self.snapshot()
        proc = self.run_sync(self.repo_a)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(proc.stdout, "", "无新增时不输出")
        swapped = RAW_TEMPLATE.replace(
            "- 用户说“先不push”，说明默认保持本地，不推送远端。\n- 用户要求提交前先跑全量测试。",
            "- 用户要求提交前先跑全量测试。\n- 用户说“先不push”，说明默认保持本地，不推送远端。",
        )
        self.write_codex(raw=swapped)
        self.run_sync(self.repo_a)
        self.assertEqual(before, self.snapshot())

    def test_new_bullet_adds_exactly_one_file_and_index_line(self) -> None:
        self.write_codex()
        self.run_sync(self.repo_a)
        before = self.snapshot()
        added = RAW_TEMPLATE.replace("- worktree 里 .memory 是软链。", "- worktree 里 .memory 是软链。\n- 新增句子 QQQQ。")
        self.write_codex(raw=added)
        proc = self.run_sync(self.repo_a)
        after = self.snapshot()
        self.assertEqual(len(set(after) - set(before)), 1)
        self.assertIn("QQQQ", self.index())
        self.assertIn("新增 1 条", proc.stdout)
        unchanged = {k: v for k, v in before.items() if k != "MEMORY.md"}
        self.assertEqual(unchanged, {k: v for k, v in after.items() if k in unchanged})

    def test_index_section_is_at_end_and_keeps_user_lines(self) -> None:
        self.write_codex()
        self.run_sync(self.repo_a)
        idx = self.index()
        self.assertTrue(idx.startswith("# 记忆索引\n\n- [用户自己的条目](own.md) — 不许动\n"), idx)
        self.assertLess(idx.index("<!-- codex-sync:begin -->"), idx.index("<!-- codex-sync:end -->"))
        self.assertTrue(idx.rstrip("\n").endswith("<!-- codex-sync:end -->"))
        lines = idx[idx.index("<!-- codex-sync:begin -->"):].splitlines()[1:-1]
        pattern = r"^- \[.+\]\(codex-[0-9A-Za-z一-鿿-]+-[0-9a-f]{6}\.md\) — (feedback|project)·\d{4}-\d{2}-\d{2}$"
        self.assertTrue(all(re.match(pattern, line) for line in lines), lines)
        self.assertLess(idx.index("·2026-09-02"), idx.index("·2026-09-01"), "按 observed_at 倒序")

    def test_handwritten_codex_prefixed_file_is_not_taken_as_generated(self) -> None:
        """认生成物按 frontmatter 的 source，不按文件名前缀：手写的 codex-*.md 不进同步段，也不被改写。"""
        hand = self.repo_a / ".memory" / "codex-memory-location.md"
        hand.write_text(
            "---\nname: codex-memory-location\ndescription: 手写条目：Codex 记忆放在哪\n"
            "metadata:\n  type: reference\n---\n\nCodex 的记忆在仓库外 ~/.codex/memories/。\n",
            encoding="utf-8",
        )
        before = hand.read_bytes()
        self.write_codex()
        self.run_sync(self.repo_a)
        idx = self.index()
        section = idx[idx.index("<!-- codex-sync:begin -->"):]
        self.assertNotIn("codex-memory-location.md", section, "手写条目不该出现在同步段")
        self.assertRegex(section, r"\]\(codex-[^)]+-[0-9a-f]{6}\.md\)", "真同步产物仍应进段")
        self.assertEqual(before, hand.read_bytes(), "手写条目不该被改写")

    def test_index_is_capped_at_60_with_warning(self) -> None:
        bullets = "\n".join(f"- 批量句子第 {i} 条。" for i in range(70))
        self.write_codex(raw=RAW_TEMPLATE.replace("- worktree 里 .memory 是软链。", bullets))
        proc = self.run_sync(self.repo_a)
        section = self.index()[self.index().index("<!-- codex-sync:begin -->"):]
        self.assertEqual(sum(line.startswith("- [") for line in section.splitlines()), 60)
        self.assertIn("另有", section)
        self.assertIn(self.WARN_MARK, proc.stderr)

    # ── T3：仓内记忆的自动提交 ──
    def track_memory(self) -> str:
        """把 .memory 纳入版本控制，返回当时的 HEAD。"""
        self.git(self.repo_a, "add", "--", ".memory")
        self.git(self.repo_a, "commit", "-q", "-m", "memory")
        return self.git(self.repo_a, "rev-parse", "HEAD").strip()

    def test_commits_memory_when_tracked_and_keeps_other_staged_changes(self) -> None:
        """.memory 已入库：同步后就地提交；index 里别人已暂存的改动不被顺手带走。"""
        head = self.track_memory()
        (self.repo_a / "other.txt").write_text("x\n", encoding="utf-8")
        self.git(self.repo_a, "add", "--", "other.txt")
        self.write_codex()
        self.run_sync(self.repo_a)
        self.assertNotEqual(head, self.git(self.repo_a, "rev-parse", "HEAD").strip(), "应产生一个提交")
        # quotePath=false：文件名含汉字时 git 默认输出八进制转义，断言会看不懂
        files = self.git(self.repo_a, "-c", "core.quotePath=false", "show", "--name-only", "--format=", "HEAD").split()
        self.assertTrue(files and all(f.startswith(".memory/") for f in files), files)
        self.assertIn("other.txt", self.git(self.repo_a, "diff", "--cached", "--name-only"), "别人已暂存的改动应还在暂存区")
        self.assertEqual("", self.git(self.repo_a, "status", "--porcelain", "--", ".memory").strip())

    def test_does_not_commit_when_memory_untracked(self) -> None:
        """.memory 未入库（如规则仓自己把它 gitignore）：只写文件，不提交。"""
        head = self.git(self.repo_a, "rev-parse", "HEAD").strip()
        self.write_codex()
        self.run_sync(self.repo_a)
        self.assertEqual(head, self.git(self.repo_a, "rev-parse", "HEAD").strip())
        self.assertIn("?? .memory/", self.git(self.repo_a, "status", "--porcelain"))

    def test_env_switch_disables_commit(self) -> None:
        head = self.track_memory()
        self.write_codex()
        with mock.patch.dict(os.environ, {"RULES_NO_MEMORY_COMMIT": "1"}):
            self.run_sync(self.repo_a)
        self.assertEqual(head, self.git(self.repo_a, "rev-parse", "HEAD").strip())

    def test_skips_commit_while_merge_in_progress(self) -> None:
        """合并进行中不提交：偏提交本身会失败，且此时提交等于替人做一半的合并。"""
        head = self.track_memory()
        (self.repo_a / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
        self.write_codex()
        proc = self.run_sync(self.repo_a)
        self.assertEqual(head, self.git(self.repo_a, "rev-parse", "HEAD").strip())
        self.assertIn(self.WARN_MARK, proc.stderr)

    def test_secrets_are_masked(self) -> None:
        self.write_codex()
        proc = self.run_sync(self.repo_a)
        texts = "\n".join(p.read_text(encoding="utf-8") for p in self.codex_files())
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", texts)
        self.assertIn("[已掩码]", texts)
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", self.index())
        self.assertIn("掩码", proc.stderr)


if __name__ == "__main__":
    unittest.main()
