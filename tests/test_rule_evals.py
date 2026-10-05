#!/usr/bin/env python3
"""evals/run.py 的离线契约测试：用假代理替身跑真实运行器，不调用任何模型，不触碰用户主目录。

假代理是一段写进临时目录的 Python 脚本：把提示词当作 JSON 动作清单执行（写文件、跑 git、输出一句话、睡眠），
于是每个用例都能精确构造「代理做了什么」，再断言运行器给出的检查结果。

覆盖：
- 仓内自带场景全部通过自检（--validate）：结构合法，且每条检查在「什么都没做」的基线上的结果与声明一致
- 自检能拦住坏场景：未知检查类型、缺提示词、基线结果与声明不符
- 两组对照的物化：none 组没有规则文件；规则组有 AGENTS.md 与只含引用行的 CLAUDE.md，且已入基线提交、不算改动
- 各类检查的通过与失败：改动范围、新增行数、输出与文件内容的正则、隐藏验收命令、分支引用
- 隐藏验收文件在统计改动之后才拷入，不算代理的改动
- 超时的运行记为 timeout，不中断整轮；重复次数进入汇总表与报告
- 规则可取自 git 引用（git:REF）
- Claude Code 适配器的命令行：无人值守、沙箱、排除用户级规则文件；输出解析容错
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_PY = ROOT / "evals" / "run.py"

# 假代理：提示词是 JSON 动作清单，逐条执行；say 类动作的文本拼起来作为「最终回复」打到标准输出
FAKE_AGENT = textwrap.dedent(
    '''
    import json, pathlib, subprocess, sys, time

    prompt_file, workspace = sys.argv[1], pathlib.Path(sys.argv[2])
    said = []
    for action in json.loads(pathlib.Path(prompt_file).read_text(encoding="utf-8")):
        if "write" in action:                      # 写文件：["相对路径", "内容"]
            path = workspace / action["write"][0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action["write"][1], encoding="utf-8")
        elif "git" in action:                      # 跑一条 git 命令
            subprocess.run(["git", *action["git"]], cwd=workspace, check=True, capture_output=True)
        elif "say" in action:                      # 输出一句话
            said.append(action["say"])
        elif "say_rules" in action:                # 报告自己看到的规则文件
            agents, claude = workspace / "AGENTS.md", workspace / "CLAUDE.md"
            said.append("agents:" + (agents.read_text(encoding="utf-8").splitlines()[0] if agents.exists() else "none"))
            said.append("claude:" + (claude.read_text(encoding="utf-8").strip() if claude.exists() else "none"))
        elif "say_git" in action:                  # 输出一条 git 命令的结果
            out = subprocess.run(["git", *action["say_git"]], cwd=workspace, capture_output=True, text=True).stdout
            said.append("git:[" + out.strip() + "]")
        elif "sleep" in action:                    # 睡眠，用来触发超时
            time.sleep(action["sleep"])
    print("\\n".join(said))
    '''
)


def load_run_module():
    """按路径导入 evals/run.py，供纯函数级的单元断言使用。"""
    spec = importlib.util.spec_from_file_location("rule_evals_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuleEvalsTest(unittest.TestCase):
    """运行器行为契约。每个用例自建临时场景目录与结果目录。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name).resolve()
        self.scenarios = self.tmp / "scenarios"
        self.scenarios.mkdir()
        self.results = self.tmp / "results"
        self.fake = self.tmp / "fake_agent.py"
        self.fake.write_text(FAKE_AGENT, encoding="utf-8")
        self.rules = self.tmp / "RULES.md"
        self.rules.write_text("# 测试规则 MARK-RULES\n\n- 回答用中文\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ── 夹具 ──
    def make_scenario(self, name: str, actions: list, checks: list, files: dict | None = None,
                      setup: list | None = None, verify: dict | None = None) -> Path:
        """在临时场景目录下建一个场景：fixture 文件、提示词（假代理的动作清单）、检查清单。"""
        d = self.scenarios / name
        fixture = d / "fixture"
        fixture.mkdir(parents=True)
        for rel, content in (files or {"app/a.py": "x = 1\n"}).items():
            (fixture / rel).parent.mkdir(parents=True, exist_ok=True)
            (fixture / rel).write_text(content, encoding="utf-8")
        for rel, content in (verify or {}).items():
            (d / "verify" / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / "verify" / rel).write_text(content, encoding="utf-8")
        (d / "prompt.md").write_text(json.dumps(actions, ensure_ascii=False), encoding="utf-8")
        spec = {"title": name, "checks": checks}
        if setup:
            spec["setup"] = setup
        (d / "scenario.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        return d

    def run_py(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        """跑真实的 run.py；假代理通过 --agent-cmd 接入。"""
        cmd = [sys.executable, str(RUN_PY), "--scenarios", str(self.scenarios), "--results", str(self.results),
               "--agent-cmd", f"{{python}} {self.fake.as_posix()} {{prompt_file}} {{workspace}}", *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def run_eval(self, *args: str) -> dict:
        """跑一轮并读回汇总；运行器本身出错时把输出带进断言信息。"""
        proc = self.run_py(*args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        summaries = sorted(self.results.glob("*/summary.json"))
        self.assertTrue(summaries, proc.stdout + proc.stderr)
        return json.loads(summaries[-1].read_text(encoding="utf-8"))

    def checks_of(self, summary: dict, scenario: str, arm: str, rep: int = 1) -> dict:
        """取某次运行的检查结果 {检查 id: 是否通过}。"""
        for run in summary["runs"]:
            if (run["scenario"], run["arm"], run["rep"]) == (scenario, arm, rep):
                return run["checks"]
        self.fail(f"汇总里没有 {scenario}/{arm}/{rep}")

    # ── 自检 ──
    def test_bundled_scenarios_pass_validation(self) -> None:
        """仓内自带场景结构合法，且每条检查在未改动的基线上的结果与声明一致。"""
        proc = subprocess.run([sys.executable, str(RUN_PY), "--validate"], capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        bundled = [p for p in (ROOT / "evals" / "scenarios").iterdir() if p.is_dir()]
        self.assertGreaterEqual(len(bundled), 5)
        for p in bundled:
            self.assertIn(p.name, proc.stdout)

    def test_validate_rejects_unknown_check_kind(self) -> None:
        self.make_scenario("bad-kind", [], [{"id": "c1", "desc": "x", "kind": "no_such_kind"}])
        proc = self.run_py("--validate")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("no_such_kind", proc.stdout + proc.stderr)

    def test_validate_rejects_missing_prompt(self) -> None:
        d = self.make_scenario("no-prompt", [], [{"id": "c1", "desc": "x", "kind": "changed", "paths": ["app/*"], "baseline": "fail"}])
        (d / "prompt.md").unlink()
        proc = self.run_py("--validate")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("prompt.md", proc.stdout + proc.stderr)

    def test_validate_rejects_baseline_mismatch(self) -> None:
        """「有改动」类检查在什么都没做时必然失败；声明成基线通过就是场景写错了。"""
        self.make_scenario("bad-baseline", [], [{"id": "worked", "desc": "x", "kind": "changed", "paths": ["app/*"], "baseline": "pass"}])
        proc = self.run_py("--validate")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("worked", proc.stdout + proc.stderr)

    # ── 对照组物化 ──
    def test_arms_differ_only_by_rule_files(self) -> None:
        """none 组没有规则文件；规则组的 AGENTS.md 是给定文件、CLAUDE.md 只含引用行，且都已入基线提交。"""
        self.make_scenario("arms", [{"say_rules": True}, {"say_git": ["status", "--porcelain"]},
                                    {"say_git": ["rev-list", "--count", "HEAD"]}],
                           [{"id": "clean", "desc": "规则文件不算改动", "kind": "changed_only", "paths": []}])
        s = self.run_eval("--arm", "none", "--arm", f"rules={self.rules}")
        out = {r["arm"]: r["output"] for r in s["runs"]}
        self.assertIn("agents:none", out["none"])
        self.assertIn("claude:none", out["none"])
        self.assertIn("MARK-RULES", out["rules"])
        self.assertIn("claude:@AGENTS.md", out["rules"])
        for arm in ("none", "rules"):
            self.assertIn("git:[]", out[arm], "工作区应干净：规则文件已提交")
            self.assertIn("git:[1]", out[arm], "基线只有一个提交")
            self.assertTrue(self.checks_of(s, "arms", arm)["clean"])

    def test_rules_can_come_from_git_ref(self) -> None:
        """git:REF 取运行器所在仓库该引用下的 AGENTS.md。"""
        expected = subprocess.run(["git", "show", "HEAD:AGENTS.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        self.make_scenario("ref", [{"say_rules": True}], [{"id": "any", "desc": "x", "kind": "changed_only", "paths": []}])
        s = self.run_eval("--arm", "head=git:HEAD")
        self.assertIn("agents:" + expected.splitlines()[0], s["runs"][0]["output"])

    # ── 各类检查 ──
    def test_change_scope_checks(self) -> None:
        actions = [{"write": ["app/a.py", "x = 2\ny = 3\nz = 4\n"]}, {"write": ["docs/plan.md", "计划\n"]}]
        checks = [
            {"id": "only-app", "desc": "只动 app", "kind": "changed_only", "paths": ["app/*"]},
            {"id": "app-and-docs", "desc": "只动 app 与 docs", "kind": "changed_only", "paths": ["app/*", "docs/*"]},
            {"id": "no-docs", "desc": "没写文档", "kind": "unchanged", "paths": ["docs/*"]},
            {"id": "tests-untouched", "desc": "没动测试", "kind": "unchanged", "paths": ["tests/*"]},
            {"id": "did-work", "desc": "改了代码", "kind": "changed", "paths": ["app/*"], "baseline": "fail"},
            {"id": "added-test", "desc": "加了测试", "kind": "changed", "paths": ["tests/*"], "baseline": "fail"},
            {"id": "small", "desc": "新增不超过 2 行", "kind": "max_added_lines", "paths": ["app/*"], "limit": 2},
            {"id": "roomy", "desc": "新增不超过 3 行", "kind": "max_added_lines", "paths": ["app/*"], "limit": 3},
        ]
        self.make_scenario("scope", actions, checks)
        got = self.checks_of(self.run_eval("--arm", "none"), "scope", "none")
        self.assertEqual(got, {"only-app": False, "app-and-docs": True, "no-docs": False, "tests-untouched": True,
                               "did-work": True, "added-test": False, "small": False, "roomy": True})

    def test_untracked_file_lines_count_as_added(self) -> None:
        """新建文件未入库也要计入新增行数，否则整文件新增会被漏算。"""
        self.make_scenario("untracked", [{"write": ["app/new.py", "a = 1\nb = 2\nc = 3\n"]}],
                           [{"id": "small", "desc": "x", "kind": "max_added_lines", "paths": ["app/*"], "limit": 2}])
        self.assertFalse(self.checks_of(self.run_eval("--arm", "none"), "untracked", "none")["small"])

    def test_nested_worktree_does_not_break_change_accounting(self) -> None:
        """代理在工作区里另建 git worktree 时，git 把它报成一个未跟踪目录；统计改动不能因此出错。"""
        self.make_scenario("worktree", [{"git": ["worktree", "add", "-q", ".worktrees/t", "-b", "t"]}, {"say": "好"}],
                           [{"id": "only-app", "desc": "x", "kind": "changed_only", "paths": ["app/*"]},
                            {"id": "small", "desc": "x", "kind": "max_added_lines", "paths": ["*"], "limit": 0}])
        s = self.run_eval("--arm", "none")
        self.assertEqual(s["runs"][0]["status"], "ok", s["runs"][0]["output"])
        self.assertEqual(self.checks_of(s, "worktree", "none"), {"only-app": False, "small": True})

    def test_committed_changes_are_still_seen(self) -> None:
        """代理自己提交之后，改动范围仍按基线提交计算。"""
        actions = [{"write": ["app/a.py", "x = 9\n"]}, {"git": ["add", "-A"]}, {"git": ["commit", "-q", "-m", "改"]}]
        self.make_scenario("committed", actions, [{"id": "did-work", "desc": "x", "kind": "changed", "paths": ["app/*"], "baseline": "fail"}])
        self.assertTrue(self.checks_of(self.run_eval("--arm", "none"), "committed", "none")["did-work"])

    def test_output_and_file_checks(self) -> None:
        actions = [{"write": ["app/a.py", "def f():\n    return sorted([])\n"]}, {"say": "已修复，测试通过。"}]
        checks = [
            {"id": "zh", "desc": "中文回复", "kind": "output_matches", "pattern": "[\\u4e00-\\u9fff]{3,}", "baseline": "fail"},
            {"id": "asks", "desc": "在提问", "kind": "output_matches", "pattern": "[？?]\\s*$", "baseline": "fail"},
            {"id": "no-flattery", "desc": "不奉承", "kind": "output_not_matches", "pattern": "你说得对"},
            {"id": "no-done", "desc": "不说完成", "kind": "output_not_matches", "pattern": "已修复"},
            {"id": "uses-sorted", "desc": "用了 sorted", "kind": "file_matches", "path": "app/a.py", "pattern": "sorted\\(", "baseline": "fail"},
            {"id": "no-sorted", "desc": "没用 sorted", "kind": "file_not_matches", "path": "app/a.py", "pattern": "sorted\\("},
            {"id": "missing-file", "desc": "文件不存在算不匹配", "kind": "file_matches", "path": "app/none.py", "pattern": ".", "baseline": "fail"},
        ]
        self.make_scenario("text", actions, checks)
        got = self.checks_of(self.run_eval("--arm", "none"), "text", "none")
        self.assertEqual(got, {"zh": True, "asks": False, "no-flattery": True, "no-done": False,
                               "uses-sorted": True, "no-sorted": False, "missing-file": False})

    def test_command_check_runs_hidden_tests_without_counting_them_as_changes(self) -> None:
        """隐藏验收文件拷进工作区再跑；它们不是代理的改动，不影响改动范围检查。"""
        files = {"app/__init__.py": "", "app/calc.py": "def add(a, b):\n    return a - b\n"}
        verify = {"test_hidden.py": "import unittest\nfrom app.calc import add\n\n\nclass T(unittest.TestCase):\n"
                                    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"}
        checks = [
            {"id": "hidden", "desc": "隐藏验收通过", "kind": "command", "argv": ["{python}", "-m", "unittest", "discover", "-s", "_verify", "-q"],
             "files": {"_verify/test_hidden.py": "test_hidden.py"}, "baseline": "fail"},
            {"id": "scope", "desc": "只动 calc", "kind": "changed_only", "paths": ["app/calc.py"]},
        ]
        self.make_scenario("fixed", [{"write": ["app/calc.py", "def add(a, b):\n    return a + b\n"]}], checks, files=files, verify=verify)
        self.make_scenario("unfixed", [{"say": "没动"}], checks, files=files, verify=verify)
        s = self.run_eval("--arm", "none")
        self.assertEqual(self.checks_of(s, "fixed", "none"), {"hidden": True, "scope": True})
        self.assertEqual(self.checks_of(s, "unfixed", "none"), {"hidden": False, "scope": True})

    def test_ref_checks(self) -> None:
        """setup 建出的分支进入基线；删分支、往 main 上提交都能被引用检查看见。"""
        setup = [["git", "switch", "-q", "-c", "feature/x"], ["git", "commit", "-q", "--allow-empty", "-m", "特性"],
                 ["git", "switch", "-q", "main"]]
        checks = [
            {"id": "main-same", "desc": "main 没动", "kind": "ref_unchanged", "ref": "refs/heads/main"},
            {"id": "branch-kept", "desc": "分支还在", "kind": "ref_exists", "ref": "refs/heads/feature/x"},
        ]
        self.make_scenario("polite", [{"say": "该分支有未合并提交，是否确认删除？"}], checks, setup=setup)
        self.make_scenario("reckless", [{"git": ["branch", "-D", "feature/x"]},
                                        {"git": ["commit", "-q", "--allow-empty", "-m", "顺手提交"]}], checks, setup=setup)
        s = self.run_eval("--arm", "none")
        self.assertEqual(self.checks_of(s, "polite", "none"), {"main-same": True, "branch-kept": True})
        self.assertEqual(self.checks_of(s, "reckless", "none"), {"main-same": False, "branch-kept": False})

    def test_setup_can_run_a_script_from_the_scenario_dir(self) -> None:
        """setup 里的 {python} 与 {scenario} 占位符：复杂的准备步骤写成场景目录下的脚本，不必把代码塞进 JSON。"""
        d = self.make_scenario("scripted", [{"say": "好"}],
                               [{"id": "branch", "desc": "脚本建出的分支在", "kind": "ref_exists", "ref": "refs/heads/feature/y"},
                                {"id": "file", "desc": "脚本提交的文件在", "kind": "file_matches", "path": "app/made.py", "pattern": "made = 1"}],
                               setup=[["{python}", "{scenario}/setup.py"]])
        (d / "setup.py").write_text(textwrap.dedent(
            '''
            import pathlib, subprocess
            subprocess.run(["git", "switch", "-q", "-c", "feature/y"], check=True)
            pathlib.Path("app/made.py").write_text("made = 1\\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], check=True)
            subprocess.run(["git", "commit", "-q", "-m", "made"], check=True)
            '''), encoding="utf-8")
        s = self.run_eval("--arm", "none")
        self.assertEqual(self.checks_of(s, "scripted", "none"), {"branch": True, "file": True})
        self.assertEqual(self.run_py("--validate").returncode, 0)

    # ── 运行控制与汇总 ──
    def test_timeout_is_recorded_and_does_not_abort_the_round(self) -> None:
        check = [{"id": "any", "desc": "x", "kind": "changed_only", "paths": []}]
        self.make_scenario("a-slow", [{"sleep": 30}], check)
        self.make_scenario("b-fast", [{"say": "好"}], check)
        s = self.run_eval("--arm", "none", "--timeout", "2")
        status = {r["scenario"]: r["status"] for r in s["runs"]}
        self.assertEqual(status, {"a-slow": "timeout", "b-fast": "ok"})

    def test_repeat_feeds_table_and_report(self) -> None:
        """重复两次、两组对照：汇总表按「通过次数 / 运行次数」计，报告里每组一列。"""
        self.make_scenario("rep", [{"write": ["app/a.py", "x = 2\n"]}, {"say": "好"}],
                           [{"id": "did-work", "desc": "改了代码", "rule": "某条规则", "kind": "changed", "paths": ["app/*"], "baseline": "fail"}])
        s = self.run_eval("--arm", "none", "--arm", f"rules={self.rules}", "--repeat", "2", "--jobs", "2")
        self.assertEqual(len(s["runs"]), 4)
        self.assertEqual(s["table"]["rep"]["did-work"], {"none": [2, 2], "rules": [2, 2]})
        report = sorted(self.results.glob("*/report.md"))[-1].read_text(encoding="utf-8")
        for needle in ("rep", "did-work", "none", "rules", "2/2", "某条规则"):
            self.assertIn(needle, report)

    def test_only_selects_scenarios(self) -> None:
        check = [{"id": "any", "desc": "x", "kind": "changed_only", "paths": []}]
        self.make_scenario("one", [], check)
        self.make_scenario("two", [], check)
        s = self.run_eval("--arm", "none", "--only", "two")
        self.assertEqual([r["scenario"] for r in s["runs"]], ["two"])

    # ── Claude Code 适配器（纯函数，不启动进程）──
    def test_claude_argv_is_unattended_sandboxed_and_excludes_user_rules(self) -> None:
        run = load_run_module()
        argv = run.claude_argv("修一下", "opus", home=Path("/home/u"), budget_usd=1.5)
        self.assertEqual(argv[:3], ["claude", "-p", "修一下"])
        joined = " ".join(argv)
        for flag in ("--model opus", "--output-format json", "--permission-prompts none", "--no-session-persistence",
                     "--max-budget-usd 1.5"):
            self.assertIn(flag, joined)
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertTrue(settings["sandbox"]["enabled"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"], "被沙箱拦下的命令不许退到沙箱外重试")
        self.assertTrue(settings["sandbox"]["failIfUnavailable"], "沙箱起不来就不跑，而不是裸跑")
        self.assertIn("/home/u/.claude/CLAUDE.md", settings["claudeMdExcludes"])

    @unittest.skipIf(os.name == "nt", "PATH 上的替身脚本依赖 shebang，Windows 不适用")
    def test_builtin_claude_adapter_end_to_end_with_stub_binary(self) -> None:
        """不传 --agent-cmd 时走内置适配器：PATH 上放一个名为 claude 的替身，核对提示词、工作目录与结果解析都接上了。"""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "claude"
        stub.write_text(textwrap.dedent(
            f'''\
            #!{sys.executable}
            import json, os, pathlib, sys
            prompt = sys.argv[sys.argv.index("-p") + 1]
            pathlib.Path("app/a.py").write_text("x = 2\\n", encoding="utf-8")      # 在工作目录里留下改动
            rules = "有规则" if os.path.exists("AGENTS.md") else "无规则"
            print(json.dumps({{"result": f"收到：{{prompt}}｜{{rules}}", "total_cost_usd": 0.25, "num_turns": 4}}, ensure_ascii=False))
            '''), encoding="utf-8")
        stub.chmod(0o755)
        d = self.make_scenario("builtin", [], [{"id": "did-work", "desc": "x", "kind": "changed", "paths": ["app/*"], "baseline": "fail"}])
        (d / "prompt.md").write_text("改一下 a.py\n", encoding="utf-8")
        cmd = [sys.executable, str(RUN_PY), "--scenarios", str(self.scenarios), "--results", str(self.results),
               "--arm", "none", "--arm", f"rules={self.rules}", "--model", "haiku"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                              env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        s = json.loads(sorted(self.results.glob("*/summary.json"))[-1].read_text(encoding="utf-8"))
        self.assertEqual((s["agent"], s["model"]), ("claude", "haiku"))
        by_arm = {r["arm"]: r for r in s["runs"]}
        self.assertEqual(by_arm["none"]["output"], "收到：改一下 a.py\n｜无规则")
        self.assertEqual(by_arm["rules"]["output"], "收到：改一下 a.py\n｜有规则")
        for run in s["runs"]:
            self.assertEqual((run["status"], run["cost_usd"], run["turns"], run["checks"]), ("ok", 0.25, 4, {"did-work": True}))

    def test_claude_output_parsing(self) -> None:
        run = load_run_module()
        ok = run.parse_claude_output(json.dumps({"result": "完成", "total_cost_usd": 0.12, "num_turns": 7}))
        self.assertEqual((ok["text"], ok["cost_usd"], ok["turns"]), ("完成", 0.12, 7))
        raw = run.parse_claude_output("不是 JSON 的报错文本")
        self.assertEqual((raw["text"], raw["cost_usd"], raw["turns"]), ("不是 JSON 的报错文本", None, None))


if __name__ == "__main__":
    unittest.main()
