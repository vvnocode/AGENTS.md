#!/usr/bin/env python3
"""规则回归集运行器：同一批场景，在「不带规则」与「带某一版规则」的对照组下各跑若干次，比较可观察的行为。

用法：
  run.py --validate                                  只做场景自检，不调用模型
  run.py                                             默认两组：none 与 rules=<仓根>/AGENTS.md，每格跑 1 次
  run.py --arm none --arm old=git:main --arm new=AGENTS.md --repeat 3 --jobs 4
  run.py --only bug-fix,small-change --model fable
  run.py --agent-cmd 'mytool exec --prompt-file {prompt_file} --cd {workspace}'   接入其他工具

背景：规则文件里矫正模型行为的条款是在替某一代模型的短板说话，模型换代后可能多余甚至反向。
这个脚本回答「这条还要不要」：某条规则对应的检查，不带规则也每次都通过，这条就是删除候选；
只有带规则才通过，就该留；带了规则仍不通过，说明条文没起作用，该改写或改用机制实现。

每次运行的步骤：
  1. 把场景的 fixture 拷进临时目录，初始化成 git 仓库；规则组在基线提交里放入 AGENTS.md 与只含引用行的 CLAUDE.md
  2. 执行场景的 setup（建分支等），记下基线提交与全部分支引用
  3. 在该目录里以无人值守方式启动代理，提示词取自场景的 prompt.md
  4. 代理结束后统计改动（相对基线提交），逐条执行场景声明的检查
  5. 产物（最终回复、diff、检查结果）落到 results/<时间戳>/<场景>/<组>-<序号>/，最后汇总成 summary.json 与 report.md

隔离：内置的 Claude Code 适配器开启沙箱（命令只能写工作目录、无网络）、不允许退到沙箱外重试、
不应答任何权限询问、不加载 MCP 与 skills，并排除用户级 ~/.claude/CLAUDE.md，使各组只差项目里的规则文件。
--agent-cmd 接入的工具由调用者自己负责隔离与排除其全局规则入口。

仅依赖标准库，Python 3.9 及以上。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import fnmatch
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_SCENARIOS = HERE / "scenarios"
DEFAULT_RESULTS = HERE / "results"

# 运行器自己做提交时用的身份；同时写进临时仓库的配置，代理在里面提交不必再配
GIT_ID = ["-c", "user.name=rule-evals", "-c", "user.email=rule-evals@example.invalid",
          "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
# 写进临时仓库 .git/info/exclude：跑测试产生的缓存、隐藏验收目录等不算代理的改动
EXCLUDES = ["__pycache__/", "*.pyc", ".pytest_cache/", ".DS_Store", "_verify/", ".claude/"]

# 检查类型 → 必填字段
CHECK_KINDS = {
    "changed_only": ("paths",),          # 所有改动的路径都落在给定通配内（空列表表示不许有任何改动）
    "unchanged": ("paths",),             # 给定通配内没有任何改动
    "changed": ("paths",),               # 给定通配内至少有一处改动
    "max_added_lines": ("paths", "limit"),  # 给定通配内新增行数之和不超过 limit
    "output_matches": ("pattern",),      # 最终回复匹配正则
    "output_not_matches": ("pattern",),  # 最终回复不匹配正则
    "file_matches": ("path", "pattern"),      # 文件存在且内容匹配正则
    "file_not_matches": ("path", "pattern"),  # 文件不存在，或内容不匹配正则
    "command": ("argv",),                # 在工作区执行命令，退出码为 0 即通过；可先拷入隐藏验收文件
    "ref_unchanged": ("ref",),           # 分支引用仍指向基线时的提交
    "ref_exists": ("ref",),              # 分支引用仍然存在
}
PRINT_LOCK = threading.Lock()


class ScenarioError(Exception):
    """场景定义有问题（结构不合法或基线自检不符）。"""


# ── 基础工具 ──
def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """在 cwd 执行一条 git 命令，带固定身份；输出按 UTF-8 解码。"""
    return subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def log(message: str) -> None:
    """并发运行时逐行输出进度，避免多线程把行打散。"""
    with PRINT_LOCK:
        print(message, flush=True)


def match_any(path: str, patterns: list) -> bool:
    """路径是否匹配任一通配；用 fnmatch 语义，* 可以跨目录。"""
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


# ── 场景加载与结构校验 ──
def load_scenario(directory: Path) -> dict:
    """读取并校验一个场景目录，返回带 name / dir / prompt 的场景字典；不合法抛 ScenarioError。"""
    name = directory.name
    spec_path = directory / "scenario.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScenarioError(f"{name}: scenario.json 读不了：{exc}")
    prompt_path = directory / "prompt.md"
    if not prompt_path.is_file() or not prompt_path.read_text(encoding="utf-8").strip():
        raise ScenarioError(f"{name}: 缺少 prompt.md 或内容为空")
    if not (directory / "fixture").is_dir():
        raise ScenarioError(f"{name}: 缺少 fixture/ 目录")
    checks = spec.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ScenarioError(f"{name}: checks 必须是非空列表")
    seen = set()
    for check in checks:
        cid, kind = check.get("id"), check.get("kind")
        if not cid or cid in seen:
            raise ScenarioError(f"{name}: 检查缺少 id 或 id 重复：{cid!r}")
        seen.add(cid)
        if kind not in CHECK_KINDS:
            raise ScenarioError(f"{name}/{cid}: 未知的检查类型 {kind!r}")
        for field in CHECK_KINDS[kind]:
            if field not in check:
                raise ScenarioError(f"{name}/{cid}: {kind} 缺少字段 {field}")
        if check.get("baseline", "pass") not in ("pass", "fail"):
            raise ScenarioError(f"{name}/{cid}: baseline 只能是 pass 或 fail")
        if "pattern" in check:
            try:
                re.compile(check["pattern"])
            except re.error as exc:
                raise ScenarioError(f"{name}/{cid}: 正则无法编译：{exc}")
        for src in (check.get("files") or {}).values():
            if not (directory / "verify" / src).is_file():
                raise ScenarioError(f"{name}/{cid}: 验收文件 verify/{src} 不存在")
    for step in spec.get("setup", []):
        if not (isinstance(step, list) and step and all(isinstance(a, str) for a in step)):
            raise ScenarioError(f"{name}: setup 的每一步必须是字符串数组（argv），当前为 {step!r}")
    spec.update(name=name, dir=directory, prompt=prompt_path.read_text(encoding="utf-8"))
    return spec


def discover(scenarios_dir: Path, only: list) -> list:
    """列出场景目录下的全部场景（按名称排序）；only 非空时只取点名的。"""
    if not scenarios_dir.is_dir():
        raise ScenarioError(f"场景目录不存在：{scenarios_dir}")
    names = sorted(p.name for p in scenarios_dir.iterdir() if (p / "scenario.json").is_file())
    if only:
        missing = [n for n in only if n not in names]
        if missing:
            raise ScenarioError(f"找不到场景：{', '.join(missing)}（现有：{', '.join(names)}）")
        names = [n for n in names if n in only]
    if not names:
        raise ScenarioError(f"{scenarios_dir} 下没有场景")
    return [load_scenario(scenarios_dir / n) for n in names]


# ── 工作区物化 ──
def materialize(scenario: dict, rules_text: str | None, workspace: Path) -> dict:
    """把场景物化成一个 git 仓库，返回基线信息 {commit, refs}。

    rules_text 非空时，基线提交里带 AGENTS.md（规则正文）与 CLAUDE.md（只含引用行 @AGENTS.md）：
    与本仓接线脚本给真实仓库写下的形态一致，各工具都读得到；入库后它们不算代理的改动。
    """
    shutil.copytree(scenario["dir"] / "fixture", workspace)
    git(workspace, "init", "-q", "-b", "main")
    for key, value in (("user.name", "rule-evals"), ("user.email", "rule-evals@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        git(workspace, "config", key, value)
    exclude = workspace / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(EXCLUDES) + "\n", encoding="utf-8")
    if rules_text is not None:
        (workspace / "AGENTS.md").write_text(rules_text, encoding="utf-8")
        (workspace / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-q", "--allow-empty", "-m", "baseline")
    # setup：场景自带的准备步骤（建分支、造未合并提交等），直接按 argv 执行，不经过 shell。
    # 占位符 {python} 换成当前解释器、{scenario} 换成场景目录：复杂步骤可以写成场景目录下的脚本
    for step in scenario.get("setup", []):
        step = [a.replace("{python}", sys.executable).replace("{scenario}", str(scenario["dir"])) for a in step]
        done = subprocess.run(step, cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode != 0:
            raise ScenarioError(f"{scenario['name']}: setup 步骤失败 {step}: {done.stderr.strip()}")
    refs = {}
    for line in git(workspace, "for-each-ref", "--format=%(refname) %(objectname)").stdout.splitlines():
        ref, sha = line.split(" ", 1)
        refs[ref] = sha
    return {"commit": git(workspace, "rev-parse", "HEAD").stdout.strip(), "refs": refs}


def collect_changes(workspace: Path, baseline_commit: str) -> dict:
    """统计相对基线提交的改动，返回 {相对路径: 新增行数}。

    已跟踪文件看基线提交到当前工作区的差异（代理自己提交过也照样算）；未跟踪文件整份算新增。
    被 .git/info/exclude 忽略的缓存文件不计。
    """
    changes: dict = {}
    numstat = git(workspace, "diff", "--numstat", "--no-renames", "-z", baseline_commit).stdout
    for record in filter(None, numstat.split("\0")):
        added, _deleted, path = record.split("\t", 2)
        changes[path] = 0 if added == "-" else int(added)   # 二进制文件的行数记为 0
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for path in filter(None, untracked.split("\0")):
        data = (workspace / path).read_bytes()
        changes[path] = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return changes


# ── 检查 ──
def eval_check(check: dict, scenario: dict, workspace: Path, output: str, changes: dict, baseline: dict) -> bool:
    """执行一条检查，返回是否通过。"""
    kind = check["kind"]
    if kind == "changed_only":
        return all(match_any(p, check["paths"]) for p in changes)
    if kind == "unchanged":
        return not any(match_any(p, check["paths"]) for p in changes)
    if kind == "changed":
        return any(match_any(p, check["paths"]) for p in changes)
    if kind == "max_added_lines":
        return sum(n for p, n in changes.items() if match_any(p, check["paths"])) <= check["limit"]
    if kind in ("output_matches", "output_not_matches"):
        found = re.search(check["pattern"], output, re.M) is not None
        return found if kind == "output_matches" else not found
    if kind in ("file_matches", "file_not_matches"):
        target = workspace / check["path"]
        found = target.is_file() and re.search(check["pattern"], target.read_text(encoding="utf-8", errors="replace"), re.M) is not None
        return found if kind == "file_matches" else not found
    if kind == "command":
        # 隐藏验收文件此刻才拷入：改动已经统计完，它们不会被算到代理头上
        for dest, src in (check.get("files") or {}).items():
            (workspace / dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(scenario["dir"] / "verify" / src, workspace / dest)
        argv = [sys.executable if a == "{python}" else a for a in check["argv"]]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            return subprocess.run(argv, cwd=workspace, capture_output=True, timeout=300, env=env).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if kind == "ref_unchanged":
        now = git(workspace, "rev-parse", "--verify", "--quiet", check["ref"], check=False).stdout.strip()
        return bool(now) and now == baseline["refs"].get(check["ref"])
    if kind == "ref_exists":
        return git(workspace, "rev-parse", "--verify", "--quiet", check["ref"], check=False).returncode == 0
    raise ScenarioError(f"未知的检查类型 {kind!r}")


def validate(scenarios: list) -> list:
    """场景自检：在「代理什么都没做、也什么都没说」的基线上执行每条检查，结果必须与声明的 baseline 一致。

    这是检查本身的红绿验证：声明 baseline=fail 的检查（如隐藏验收、「确实动了代码」）在基线上必须失败，
    否则它在真实运行里通过也说明不了任何事。返回问题列表，空表示全部一致。
    """
    problems = []
    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="rule-eval-") as tmp:
            workspace = Path(tmp) / "ws"
            baseline = materialize(scenario, None, workspace)
            changes = collect_changes(workspace, baseline["commit"])
            for check in scenario["checks"]:
                expected = check.get("baseline", "pass") == "pass"
                actual = eval_check(check, scenario, workspace, "", changes, baseline)
                if actual != expected:
                    problems.append(f"{scenario['name']}/{check['id']}: 基线上应{'通过' if expected else '失败'}，实际{'通过' if actual else '失败'}")
    return problems


# ── 代理适配 ──
def claude_argv(prompt: str, model: str, home: Path, budget_usd: float | None = None) -> list:
    """拼出 Claude Code 无人值守运行的命令行。

    - 沙箱开启且不许退到沙箱外重试：命令只能写工作目录、没有网络；沙箱起不来就不跑
    - 不应答权限询问：会弹询问的操作一律拒绝，编辑工作目录内的文件自动放行
    - 排除用户级 CLAUDE.md（及其软链目标）：各组之间只差项目里的规则文件
    - 不加载 MCP 与 skills、不保存会话：减少与规则无关的变量，也不往会话列表里留记录
    """
    user_rules = home / ".claude" / "CLAUDE.md"
    settings = {
        "sandbox": {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True},
        "claudeMdExcludes": sorted({str(user_rules), str(Path(os.path.realpath(user_rules)))}),
    }
    argv = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
            "--permission-mode", "acceptEdits", "--permission-prompts", "none",
            "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
            "--settings", json.dumps(settings, ensure_ascii=False)]
    if budget_usd:
        argv += ["--max-budget-usd", str(budget_usd)]
    return argv


def parse_claude_output(stdout: str) -> dict:
    """解析 claude -p --output-format json 的结果；不是 JSON 时把原文当作最终回复。"""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return {"text": str(data.get("result") or ""), "cost_usd": data.get("total_cost_usd"), "turns": data.get("num_turns")}
    except ValueError:
        pass
    return {"text": stdout.strip(), "cost_usd": None, "turns": None}


def run_process(argv: list, cwd: Path, timeout: int) -> tuple:
    """启动代理进程并等待，返回 (状态, stdout, stderr, 秒数)。

    状态：ok（退出码 0）、agent_error（非 0 或启动失败）、timeout（超时，整个进程组被杀掉）。
    标准输入接空设备，避免代理等待输入。
    """
    start = time.monotonic()
    kwargs = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  text=True, encoding="utf-8", errors="replace")
    if os.name != "nt":
        kwargs["start_new_session"] = True   # 自成进程组，超时可以连同子进程一起杀
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        return "agent_error", "", f"启动失败：{exc}", time.monotonic() - start
    try:
        out, err = proc.communicate(timeout=timeout)
        status = "ok" if proc.returncode == 0 else "agent_error"
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        out, err = proc.communicate()
        status = "timeout"
    return status, out, err, time.monotonic() - start


def run_agent(args: argparse.Namespace, prompt: str, prompt_file: Path, workspace: Path) -> dict:
    """按所选适配器跑一次代理，返回 {status, text, stdout, stderr, seconds, cost_usd, turns}。"""
    if args.agent_cmd:
        # 自定义命令模板：先按 shell 规则切分，再逐个替换占位符，路径里有空格也不会被拆开
        subst = {"{python}": sys.executable, "{prompt_file}": str(prompt_file), "{workspace}": str(workspace), "{model}": args.model or ""}
        argv = [subst.get(token, token) for token in shlex.split(args.agent_cmd)]
        status, out, err, seconds = run_process(argv, workspace, args.timeout)
        parsed = {"text": out.strip(), "cost_usd": None, "turns": None}
    else:
        argv = claude_argv(prompt, args.model or "opus", Path.home(), args.budget_usd)
        status, out, err, seconds = run_process(argv, workspace, args.timeout)
        parsed = parse_claude_output(out)
    return {"status": status, "stdout": out, "stderr": err, "seconds": round(seconds, 1), **parsed}


# ── 单次运行与汇总 ──
def run_one(args: argparse.Namespace, scenario: dict, arm: str, rules_text: str | None, rep: int, out_root: Path) -> dict:
    """物化 → 跑代理 → 统计改动 → 执行检查 → 落产物。返回进入汇总的一条记录。"""
    tmp = Path(tempfile.mkdtemp(prefix="rule-eval-"))
    workspace = tmp / "ws"
    record = {"scenario": scenario["name"], "arm": arm, "rep": rep}
    try:
        baseline = materialize(scenario, rules_text, workspace)
        prompt_file = tmp / "prompt.md"            # 放在工作区之外，不算改动
        prompt_file.write_text(scenario["prompt"], encoding="utf-8")
        result = run_agent(args, scenario["prompt"], prompt_file, workspace)
        checks: dict = {}
        changes: dict = {}
        if result["status"] != "timeout":
            # 代理异常退出（如触到预算上限）时工作可能做了一半，照样检查并如实记录状态
            changes = collect_changes(workspace, baseline["commit"])
            for check in scenario["checks"]:
                checks[check["id"]] = eval_check(check, scenario, workspace, result["text"], changes, baseline)
        # 产物
        out_dir = out_root / scenario["name"] / f"{arm}-{rep}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "output.txt").write_text(result["text"], encoding="utf-8")
        (out_dir / "agent_stdout.txt").write_text(result["stdout"], encoding="utf-8")
        (out_dir / "agent_stderr.txt").write_text(result["stderr"], encoding="utf-8")
        (out_dir / "diff.patch").write_text(git(workspace, "diff", baseline["commit"], check=False).stdout, encoding="utf-8")
        (out_dir / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
        record.update(status=result["status"], seconds=result["seconds"], cost_usd=result["cost_usd"],
                      turns=result["turns"], output=result["text"], checks=checks)
    except Exception as exc:  # 单次运行自身出错（如 setup 失败）只记一条，不拖垮整轮
        record.update(status="runner_error", seconds=0, cost_usd=None, turns=None, output=f"运行器出错：{exc}", checks={})
    finally:
        if args.keep:
            log(f"  保留工作区 {workspace}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for v in record["checks"].values() if v)
    log(f"  {scenario['name']} / {arm} #{rep}: {record['status']}，检查 {passed}/{len(scenario['checks'])}，{record['seconds']} 秒")
    return record


def build_table(scenarios: list, arms: list, runs: list) -> dict:
    """汇总成 {场景: {检查 id: {组: [通过次数, 运行次数]}}}；超时的运行计入运行次数、不计通过。"""
    table: dict = {}
    for scenario in scenarios:
        rows = table.setdefault(scenario["name"], {})
        for check in scenario["checks"]:
            cells = rows.setdefault(check["id"], {arm: [0, 0] for arm in arms})
            for run in runs:
                if run["scenario"] == scenario["name"]:
                    cells[run["arm"]][1] += 1
                    cells[run["arm"]][0] += 1 if run["checks"].get(check["id"]) else 0
    return table


def render_report(meta: dict, scenarios: list, arms: list, runs: list, table: dict) -> str:
    """生成 Markdown 报告：每个场景一张检查表，外加开销表与两份清单。"""
    lines = [f"# 规则回归集结果 {meta['started']}", "",
             f"代理 {meta['agent']}，模型 {meta['model']}，每格重复 {meta['repeat']} 次。单元格是「通过次数/运行次数」。", ""]
    for scenario in scenarios:
        lines += [f"## {scenario['name']} {scenario.get('title', '')}".rstrip(), "",
                  "| 检查 | 对应规则 | " + " | ".join(arms) + " |", "|---|---|" + "---|" * len(arms)]
        for check in scenario["checks"]:
            cells = table[scenario["name"]][check["id"]]
            lines.append(f"| {check['id']} {check.get('desc', '')} | {check.get('rule', '—')} | "
                         + " | ".join(f"{cells[a][0]}/{cells[a][1]}" for a in arms) + " |")
        lines.append("")
    # 开销：规则文件本身也有成本，按组看平均耗时、轮数与费用
    lines += ["## 开销", "", "| 组 | 运行数 | 非正常结束 | 平均耗时（秒） | 平均轮数 | 平均费用（USD） |", "|---|---|---|---|---|---|"]
    for arm in arms:
        mine = [r for r in runs if r["arm"] == arm]
        def mean(key: str) -> str:
            values = [r[key] for r in mine if r.get(key) is not None]
            return f"{sum(values) / len(values):.2f}" if values else "—"
        lines.append(f"| {arm} | {len(mine)} | {sum(1 for r in mine if r['status'] != 'ok')} | {mean('seconds')} | {mean('turns')} | {mean('cost_usd')} |")
    lines.append("")
    # 两份清单只看标了对应规则的检查：一份是删除候选，一份是带了规则仍没做到的
    if "none" in arms:
        redundant = [f"- {s['name']}/{c['id']}（{c['rule']}）" for s in scenarios for c in s["checks"] if c.get("rule")
                     and table[s["name"]][c["id"]]["none"][1] and table[s["name"]][c["id"]]["none"][0] == table[s["name"]][c["id"]]["none"][1]]
        lines += ["## 不带规则也每次通过的检查", "", "对应条款是删除候选；重复次数少时先加大 --repeat 再下结论。", "", *(redundant or ["- 无"]), ""]
    for arm in [a for a in arms if a != "none"]:
        failing = [f"- {s['name']}/{c['id']}（{c['rule']}）：{table[s['name']][c['id']][arm][0]}/{table[s['name']][c['id']][arm][1]}"
                   for s in scenarios for c in s["checks"] if c.get("rule")
                   and table[s["name"]][c["id"]][arm][0] < table[s["name"]][c["id"]][arm][1]]
        lines += [f"## 带规则（{arm}）仍未每次通过的检查", "", "条文没有起到作用：改写、补理由，或改用钩子等机制实现。", "", *(failing or ["- 无"]), ""]
    return "\n".join(lines)


def parse_arms(specs: list) -> dict:
    """解析 --arm：none 表示不带规则；NAME=路径 读文件；NAME=git:REF 读本仓该引用下的 AGENTS.md。"""
    arms: dict = {}
    for spec in specs or ["none", f"rules={REPO / 'AGENTS.md'}"]:
        name, sep, source = spec.partition("=")
        if not sep:
            if name != "none":
                raise ScenarioError(f"--arm {spec}: 除 none 外必须写成 名称=规则文件 或 名称=git:引用")
            arms[name] = None
        elif source.startswith("git:"):
            shown = subprocess.run(["git", "show", f"{source[4:]}:AGENTS.md"], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
            if shown.returncode != 0:
                raise ScenarioError(f"--arm {spec}: 读不到 {source[4:]}:AGENTS.md：{shown.stderr.strip()}")
            arms[name] = shown.stdout
        else:
            path = Path(source).expanduser()
            if not path.is_file():
                raise ScenarioError(f"--arm {spec}: 规则文件不存在")
            arms[name] = path.read_text(encoding="utf-8")
    return arms


def main() -> int:
    parser = argparse.ArgumentParser(description="规则回归集：带规则与不带规则对照运行同一批场景")
    parser.add_argument("--validate", action="store_true", help="只做场景自检（结构与基线红绿），不调用模型")
    parser.add_argument("--arm", action="append", metavar="NAME[=SOURCE]",
                        help="对照组，可重复：none | 名称=规则文件 | 名称=git:引用。缺省为 none 与 rules=<仓根>/AGENTS.md")
    parser.add_argument("--only", default="", help="只跑点名的场景，逗号分隔")
    parser.add_argument("--repeat", type=int, default=1, help="每个场景每组重复的次数（默认 1）")
    parser.add_argument("--jobs", type=int, default=1, help="并发运行数（默认 1）")
    parser.add_argument("--timeout", type=int, default=900, help="单次运行的超时秒数（默认 900）")
    parser.add_argument("--model", default=None, help="交给代理的模型名；Claude Code 适配器缺省为 opus")
    parser.add_argument("--budget-usd", type=float, default=None, help="单次运行的费用上限（仅 Claude Code 适配器）")
    parser.add_argument("--agent-cmd", default=None,
                        help="自定义代理命令模板，占位符 {prompt_file} {workspace} {model} {python}；在工作区内执行，标准输出即最终回复")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS, help="场景目录")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="结果目录")
    parser.add_argument("--keep", action="store_true", help="保留每次运行的临时工作区，便于人工查看")
    args = parser.parse_args()

    try:
        scenarios = discover(args.scenarios, [n for n in args.only.split(",") if n])
        if args.validate:
            problems = validate(scenarios)
            for scenario in scenarios:
                print(f"· {scenario['name']}：{len(scenario['checks'])} 条检查")
            for problem in problems:
                print(f"✗ {problem}")
            print("✓ 场景自检通过" if not problems else f"✗ {len(problems)} 处与声明不符")
            return 1 if problems else 0
        arms = parse_arms(args.arm)
    except ScenarioError as exc:
        print(f"✗ {exc}")
        return 1

    started = datetime.datetime.now().astimezone()          # 本地时区
    out_root = args.results / started.strftime("%Y%m%d-%H%M%S")
    out_root.mkdir(parents=True, exist_ok=True)
    meta = {"started": started.strftime("%Y-%m-%d %H:%M %z"), "agent": "custom" if args.agent_cmd else "claude",
            "model": args.model or ("" if args.agent_cmd else "opus"), "repeat": args.repeat, "arms": list(arms)}
    jobs = [(s, arm, text, rep) for s in scenarios for arm, text in arms.items() for rep in range(1, args.repeat + 1)]
    log(f"═══ 规则回归集：{len(scenarios)} 个场景 × {len(arms)} 组 × {args.repeat} 次 = {len(jobs)} 次运行 ═══")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_one, args, s, arm, text, rep, out_root) for s, arm, text, rep in jobs]
        runs = [f.result() for f in futures]            # 按提交顺序收集，汇总里的顺序稳定

    table = build_table(scenarios, list(arms), runs)
    (out_root / "summary.json").write_text(json.dumps({**meta, "runs": runs, "table": table}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_report(meta, scenarios, list(arms), runs, table)
    (out_root / "report.md").write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"产物目录：{out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
