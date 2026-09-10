#!/usr/bin/env python3
"""memory-sync.py：把 Codex 自带记忆里属于本仓库的部分，转写成 .memory/ 下与 Claude 自动记忆同形的条目。

用法：memory-sync.py [仓库路径]      缺省为当前所在 git 仓库；对附属 worktree 执行时落点是主工作区的 .memory/

输入：$CODEX_HOME/memories/raw_memories.md（按线程分块）与 rollout_summaries/*.md（按会话一文件）。两者每条都带 cwd。
输出：<仓根>/.memory/codex-<task_group>-<hash10>.md，一个列表项一条；MEMORY.md 末尾标记段内每条一行索引。
不做：不反向写 Codex 存储；不删除来源已消失的条目；不改写句子（只做凭证掩码）。
退出码恒为 0（钩子里调用，不能影响会话）；解析问题写 stderr。
兼容 Python 3.8+，仅标准库。设计见 docs/specs/2026-09-09-工具记忆同步回项目-design.md 第 5 节。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ── 常量（与 spec 第 5 节一致）──
LABEL_TYPE = {                                   # Codex 标签 → .memory 的 type
    "Preference signals": "feedback",            # 用户如何要求干活
    "Failures and how to do differently": "feedback",   # 纠正过的做法
    "Reusable knowledge": "project",             # 该仓的事实与约束
}
DROP_LABELS = {"References"}                     # 认识但丢弃：Codex 内部指针
BEGIN, END = "<!-- codex-sync:begin -->", "<!-- codex-sync:end -->"
MAX_INDEX = 60                                   # Claude 开局只读索引前 200 行，同步段必须封顶
ASCII = os.environ.get("MEMORY_SYNC_ASCII") == "1"   # .ps1 包装设置：输出前缀改 ASCII
DOT, WARN = ("*", "!") if ASCII else ("·", "⚠")
# 凭证掩码模式：与 llm-wiki release-check.sh 同一组；Codex 自己会脱敏，这是入库前的第二道闸
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{15,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"((?:password|passwd|token|secret)\s*[:=]\s*)([^\s<{$#，。；]+)", re.I),
]
RAW_TASK_RE = re.compile(r"^### Task \d+:\s*(.*)$")       # raw 块里的任务标题
ROLLOUT_TASK_RE = re.compile(r"^## Task \d+:\s*(.*)$")    # 会话摘要里的任务标题


def warn(msg: str) -> None:
    print(f"{WARN} {msg}", file=sys.stderr)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def real(p) -> str:
    """路径归一：解软链、去尾斜杠；macOS 的 /tmp、/var 是软链，比较前必须归一。"""
    return os.path.realpath(str(p)).rstrip("/\\")


def repo_root(path: Path) -> Optional[Path]:
    """主工作区路径（worktree list 首行）；不在 git 仓内返回 None。"""
    try:
        first = git(path, "worktree", "list", "--porcelain").splitlines()[0]
    except (subprocess.CalledProcessError, IndexError, FileNotFoundError):
        return None
    return Path(real(first[len("worktree "):]))


def candidate_cwds(root: Path) -> Tuple[Set[str], Tuple[str, ...]]:
    """精确命中集合（根 + 现存 worktree）与前缀集合（已删 worktree 的常见落点）。"""
    exact = {real(root)}
    for line in git(root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            exact.add(real(line[len("worktree "):]))
    prefixes = (real(root / ".worktrees") + os.sep, real(root / ".claude" / "worktrees") + os.sep)
    return exact, prefixes


def belongs(cwd: str, exact: Set[str], prefixes: Tuple[str, ...]) -> bool:
    c = real(cwd)
    return c in exact or any(c.startswith(p) for p in prefixes)


# ── 解析 ──
def header_fields(lines: List[str]) -> Dict[str, str]:
    """连续的裸 `key: value` 行（到第一个空行为止）。"""
    out: Dict[str, str] = {}
    for line in lines:
        if not line.strip():
            break
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def parse_tasks(body: List[str], task_re: "re.Pattern[str]") -> List[Tuple[str, str, str]]:
    """把任务正文切成 (标签, 句子, 任务标题) 三元组；只认三个标签下的列表项，其余行忽略。"""
    items: List[Tuple[str, str, str]] = []
    label: Optional[str] = None
    title = ""
    cur: Optional[str] = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and label in LABEL_TYPE:
            items.append((label, cur.strip(), title))
        cur = None

    for line in body:
        m = task_re.match(line)
        if m:
            flush()
            label = None
            title = m.group(1).strip()
            continue
        m = re.match(r"^([A-Za-z][A-Za-z ]+):\s*$", line)
        if m and (m.group(1) in LABEL_TYPE or m.group(1) in DROP_LABELS):
            flush()
            label = m.group(1)
            continue
        if label is None:
            continue
        if re.match(r"^- ", line):
            flush()
            cur = line[2:]
        elif cur is not None and line.startswith("  ") and line.strip():
            cur += " " + line.strip()                  # 续行
        elif not line.strip():
            flush()                                    # 空行结束当前列表项，标签仍有效（Codex 段间常有空行）
        else:
            flush()
            label = None                               # 标签块被别的内容打断
    flush()
    return items


def parse_raw(text: str) -> List[dict]:
    """raw_memories.md → 线程列表：{thread_id, updated_at, cwd, description, task_group, items}。"""
    threads: List[dict] = []
    for block in re.split(r"^## Thread ", text, flags=re.M)[1:]:
        lines = block.splitlines()
        thread_id = lines[0].strip().strip("`")
        head = header_fields(lines[1:])
        meta: Dict[str, str] = {}
        dashes = [i for i, l in enumerate(lines) if l.strip() == "---"]     # `---` 夹住的元数据段
        if len(dashes) >= 2:
            meta = header_fields(lines[dashes[0] + 1:dashes[1]])
            body = lines[dashes[1] + 1:]
        else:
            body = lines[1:]
        if "cwd" not in head:
            warn(f"raw 线程 {thread_id[:8]} 缺 cwd，跳过")
            continue
        threads.append({
            "kind": "raw", "thread_id": thread_id, "updated_at": head.get("updated_at", ""), "cwd": head["cwd"],
            "description": meta.get("description", ""), "task_group": meta.get("task_group", ""),
            "items": parse_tasks(body, RAW_TASK_RE),
        })
    return threads


def parse_rollout(text: str) -> Optional[dict]:
    """rollout_summaries/*.md → 一个线程来源；头部缺 thread_id 或 cwd 返回 None。"""
    lines = text.splitlines()
    head = header_fields(lines)
    if "thread_id" not in head or "cwd" not in head:
        return None
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    return {
        "kind": "rollout", "thread_id": head["thread_id"], "updated_at": head.get("updated_at", ""), "cwd": head["cwd"],
        "description": title, "task_group": "",
        "items": parse_tasks(lines, ROLLOUT_TASK_RE),
    }


# ── 转写 ──
def normalize(sentence: str) -> str:
    """去重键：NFKC 归一、压空白、中英标点归一。"""
    s = unicodedata.normalize("NFKC", sentence)
    s = re.sub(r"\s+", " ", s).strip()
    return s.translate(str.maketrans("，。；：！？（）「」“”‘’", ",.;:!?()\"\"\"\"''"))


def mask(sentence: str) -> Tuple[str, int]:
    """凭证掩码：命中的值换成 [已掩码]，返回 (句子, 命中数)。"""
    n = 0
    for pat in SECRET_PATTERNS:
        def rep(m: "re.Match[str]") -> str:
            nonlocal n
            n += 1
            return (m.group(1) + "[已掩码]") if m.lastindex else "[已掩码]"
        sentence = pat.sub(rep, sentence)
    return sentence, n


def slug(s: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or fallback


def yaml_str(s: str) -> str:
    """frontmatter 里的字符串一律双引号 + 转义，避免冒号、井号被当语法。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(entry: dict) -> str:
    """一条记忆文件：frontmatter 与 Claude 自动记忆同形，正文一句原话加一行来源。"""
    desc = entry["sentence"] if len(entry["sentence"]) <= 80 else entry["sentence"][:79] + "…"
    date = entry["observed_at"][:10] or "日期未知"
    return (
        "---\n"
        f"name: {entry['name']}\n"
        f"description: {yaml_str(desc)}\n"
        "metadata:\n"
        f"  type: {entry['type']}\n"
        "  source: codex\n"
        f"  thread_id: {entry['thread_id']}\n"
        f"  observed_at: {entry['observed_at']}\n"
        "---\n\n"
        f"{entry['sentence']}\n\n"
        f"来源：Codex 会话「{entry['description'] or entry['thread_id'][:8]}」，{date}。\n"
    )


def build_entries(sources: List[dict]) -> Tuple[List[dict], int]:
    """按句子去重、生成条目；返回 (条目, 掩码计数)。

    - 分组名按线程统一：任一来源带 task_group 就全线程沿用，缺则用 thread 前 8 位。
    - 线程有 raw 块时，它的会话摘要整份不取：raw 块是 Codex 对同一 rollout 做的记忆提取，摘要是叙事复述，
      换个说法的同一事实按句子去重抓不到（阳性对照里条目翻倍）；只有没有 raw 块的线程才用摘要。
    - 来源按 updated_at 升序处理（相同则 raw 先于摘要），首次出现的句子为准。
    """
    groups: Dict[str, str] = {}
    has_raw: Set[str] = set()
    for src in sources:
        if src["task_group"] and src["thread_id"] not in groups:
            groups[src["thread_id"]] = src["task_group"]
        if src["kind"] == "raw":
            has_raw.add(src["thread_id"])
    seen: Dict[str, dict] = {}
    masked = 0
    for src in sorted(sources, key=lambda s: (s["updated_at"], 0 if s["kind"] == "raw" else 1)):
        tid = src["thread_id"]
        if src["kind"] == "rollout" and tid in has_raw:
            continue
        group = slug(groups.get(tid, ""), tid[:8])
        for label, sentence, _title in src["items"]:
            sentence, n = mask(sentence)
            masked += n
            key = normalize(sentence)
            if not key or key in seen:
                continue
            h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
            seen[key] = {
                "name": f"codex-{group}-{h}", "sentence": sentence, "type": LABEL_TYPE[label],
                "thread_id": tid, "observed_at": src["updated_at"], "description": src["description"],
            }
    return list(seen.values()), masked


def entries_on_disk(memory: Path) -> List[dict]:
    """读回已有的 codex-*.md 供索引用（索引总是反映磁盘全集，用户删了文件下次就收敛）。"""
    out: List[dict] = []
    for p in sorted(memory.glob("codex-*.md")):
        parts = p.read_text(encoding="utf-8").split("---\n")
        if len(parts) < 3:
            continue
        fm = dict(re.findall(r"^\s*([a-z_]+): (.*)$", parts[1], flags=re.M))
        desc = fm.get("description", "").strip('"').replace('\\"', '"')
        out.append({"name": p.stem, "type": fm.get("type", "reference"), "observed_at": fm.get("observed_at", ""),
                    "desc60": desc if len(desc) <= 60 else desc[:59] + "…"})
    return out


def rebuild_index(memory: Path, entries: List[dict]) -> bool:
    """重生成标记段；返回是否写了文件。段外内容一字不动；没有标记段就追加到末尾。"""
    index = memory / "MEMORY.md"
    text = index.read_text(encoding="utf-8") if index.exists() else "# 记忆索引\n\n"
    ordered = sorted(entries, key=lambda e: e["observed_at"], reverse=True)
    lines = [f"- [{e['desc60']}]({e['name']}.md) — {e['type']}·{e['observed_at'][:10]}" for e in ordered]
    if len(lines) > MAX_INDEX:
        rest = len(lines) - MAX_INDEX
        lines = lines[:MAX_INDEX] + [f"- 另有 {rest} 条 codex-*.md 未列入索引，按需 `ls .memory/codex-*`"]
        warn(f"Codex 同步索引超过 {MAX_INDEX} 行，已截断 {rest} 条，建议清理过时条目")
    section = "\n".join([BEGIN, *lines, END]) + "\n"
    if BEGIN in text and END in text:
        before = text[:text.index(BEGIN)]
        after = text[text.index(END) + len(END):].lstrip("\n")
        new = before + section + after
    else:
        new = text.rstrip("\n") + "\n\n" + section
    if new == text:
        return False
    index.write_text(new, encoding="utf-8")
    return True


def main(argv: List[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    root = repo_root(target)
    if root is None:
        return 0                                       # 不在 git 仓内：钩子在任意目录都可能触发，静默
    memory = root / ".memory"
    if not memory.is_dir():
        return 0                                       # 未接线的仓库，静默
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    mem_dir = codex_home / "memories"
    if not mem_dir.is_dir():
        return 0
    exact, prefixes = candidate_cwds(root)
    sources: List[dict] = []
    raw = mem_dir / "raw_memories.md"
    if raw.is_file():
        sources += [t for t in parse_raw(raw.read_text(encoding="utf-8", errors="replace"))
                    if belongs(t["cwd"], exact, prefixes)]
    summaries = mem_dir / "rollout_summaries"
    for f in sorted(summaries.glob("*.md")) if summaries.is_dir() else []:
        r = parse_rollout(f.read_text(encoding="utf-8", errors="replace"))
        if r is None:
            warn(f"rollout 摘要 {f.name} 缺 thread_id 或 cwd，跳过")
            continue
        if belongs(r["cwd"], exact, prefixes):
            sources.append(r)
    entries, masked = build_entries(sources)
    added = 0
    for e in entries:
        path = memory / f"{e['name']}.md"
        if path.exists():
            continue                                   # 文件名即内容哈希：存在即同一句子，不重写
        path.write_text(render(e), encoding="utf-8")
        added += 1
    if masked:
        warn(f"{masked} 处疑似凭证已掩码")
    rebuild_index(memory, entries_on_disk(memory))
    if added:
        print(f"{DOT} Codex 记忆同步：新增 {added} 条（.memory/codex-*.md）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:                           # 钩子里跑，任何异常都不能影响会话
        warn(f"memory-sync 异常：{exc}")
        sys.exit(0)
