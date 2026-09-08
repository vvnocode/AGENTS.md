#!/usr/bin/env bash
# agent-memory-setup：让 Claude Code / Codex / dsh / opencode 在同一仓库共用一份指令（AGENTS.md）与一份仓内记忆（.memory/）。
#
# 用法见 --help。不需要 clone 本仓，可直接 curl | bash 执行；也可从已安装的 skill 目录运行。
set -euo pipefail

RAW_BASE="https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup"
usage() {
    cat <<USAGE
用法：setup.sh [仓库路径] [--with-rule]

  仓库路径     缺省为当前所在 git 仓库根
  --with-rule  往 AGENTS.md 追加「项目记忆」节。跨工具全局规则（如 vvnocode/AGENTS.md 的「项目记忆」节）已经约束
               「仓内 .memory/ 存在时怎么读写」，装了它的机器不必每仓再写一份；只给没有全局规则的协作者用的仓库才需要。

不需要 clone 本仓，在目标仓库目录下直接执行：
  curl -fsSL $RAW_BASE/setup.sh | bash -s -- [仓库路径] [--with-rule]

幂等：已就位的项不动、只补缺；不删除、不覆盖已有内容。无法自动裁定的冲突（如 AGENTS.md 与 CLAUDE.md 都是
普通文件且内容不同）只告警交人工，其余步骤照做。Windows 用同目录 setup.ps1。
USAGE
}

# 脚本所在目录须在 cd 之前解析：$0 可能是相对路径；管道运行时 $0 是 bash，解析结果无意义，后面按文件是否存在兜底
SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P || true)
WRITE_RULE=0
ROOT=""
for arg in "$@"; do
    case "$arg" in
        --with-rule) WRITE_RULE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) ROOT="$arg" ;;
    esac
done
if [ -z "$ROOT" ]; then
    ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "✗ 当前目录不在 git 仓库内，请显式传仓库路径"; exit 1; }
fi
ROOT=$(cd "$ROOT" && pwd -P)
cd "$ROOT"
command -v python3 >/dev/null || { echo "✗ 需要 python3（用于安全合并 settings.local.json）"; exit 1; }

WARN=0
ok()   { echo "· $*"; }
warn() { echo "⚠ $*"; WARN=$((WARN + 1)); }

echo "═══ agent-memory-setup：$ROOT ═══"

# ── 1) 指令合一：AGENTS.md 为正本，CLAUDE.md 只含一行 @AGENTS.md 引用 ──
# Claude Code 只读 CLAUDE.md、不读 AGENTS.md；Codex / dsh / opencode 读 AGENTS.md。两份都要有、且必须是同一份。
# 用引用行而不是软链：不需要任何权限，检出到 Windows 也有效；软链入库后在 Windows 默认 core.symlinks=false 下
# 会变成只含 "AGENTS.md" 四个字的文本文件。旧做法留下的软链在这里自动改为引用行。
IMPORT_LINE='@AGENTS.md'
write_import() { printf '%s\n' "$IMPORT_LINE" > CLAUDE.md; }
if [ -L AGENTS.md ]; then
    warn "AGENTS.md 本身是软链（指向 $(readlink AGENTS.md)），未改动：请把正本改为 AGENTS.md 后重跑"
elif [ -L CLAUDE.md ]; then
    if [ "$(readlink CLAUDE.md)" = "AGENTS.md" ]; then
        rm CLAUDE.md && write_import
        ok "CLAUDE.md 由软链改为引用行 @AGENTS.md（旧做法迁移）"
    else
        warn "CLAUDE.md 是指向 $(readlink CLAUDE.md) 的软链，未改动：请确认它最终指向 AGENTS.md"
    fi
elif [ -f CLAUDE.md ] && [ -f AGENTS.md ]; then
    if grep -qx "$IMPORT_LINE" CLAUDE.md; then
        ok "CLAUDE.md 已引用 AGENTS.md"
    elif cmp -s CLAUDE.md AGENTS.md; then
        write_import
        ok "CLAUDE.md 与 AGENTS.md 同内容：已改为引用行"
    else
        warn "AGENTS.md 与 CLAUDE.md 都是普通文件且内容不同，未改动：请人工把 CLAUDE.md 内容并入 AGENTS.md，再把 CLAUDE.md 改为只含一行 @AGENTS.md"
    fi
elif [ -f CLAUDE.md ]; then
    mv CLAUDE.md AGENTS.md && write_import
    ok "只有 CLAUDE.md：已改名为 AGENTS.md，并写 CLAUDE.md 引用行"
elif [ -f AGENTS.md ]; then
    write_import
    ok "已写 CLAUDE.md 引用行 @AGENTS.md"
else
    printf '# AGENTS.md\n\n项目指令正本；`CLAUDE.md` 只含一行 `@AGENTS.md` 引用本文件，两者永远同一份。\n' > AGENTS.md
    write_import
    ok "已新建 AGENTS.md 与 CLAUDE.md 引用行"
fi

# ── 2) 仓内记忆目录 ──
mkdir -p .memory
if [ -f .memory/MEMORY.md ]; then
    ok ".memory/MEMORY.md 已存在"
else
    printf '# 记忆索引\n\n' > .memory/MEMORY.md
    ok "已建 .memory/MEMORY.md"
fi

# ── 3) Claude Code：autoMemoryDirectory 指向仓内 .memory（绝对路径，写在不入库的 settings.local.json）──
# 只能写 settings.local.json：官方文档标明该项在入库的 settings.json 里会因安全被忽略。
mkdir -p .claude
python3 - "$ROOT" <<'PY'
import json, pathlib, sys
root = sys.argv[1]
path = pathlib.Path(".claude/settings.local.json")
want = f"{root}/.memory"
cur = {}
if path.exists():
    try:
        cur = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        sys.exit(f"✗ {path} 不是合法 JSON，请先修复")
if cur.get("autoMemoryDirectory") == want:
    print(f"· {path} 已指向 {want}")
else:
    cur["autoMemoryDirectory"] = want          # 只改这一个键，其余本机配置原样保留
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"· 已写 {path}（autoMemoryDirectory → {want}）")
PY

# ── 4) .gitignore：settings.local.json 含本机绝对路径，不入库 ──
if [ -f .gitignore ] && grep -qxF '.claude/settings.local.json' .gitignore; then
    ok ".gitignore 已含 .claude/settings.local.json"
else
    [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore)" ] && echo >> .gitignore   # 补末尾换行
    printf '# Claude 本机配置，含绝对路径，不入库（agent-memory-setup）\n.claude/settings.local.json\n' >> .gitignore
    ok "已在 .gitignore 追加 .claude/settings.local.json"
fi

# ── 5) Codex：记忆目录不可配置（固定 $CODEX_HOME/memories），只能把它自带记忆整体关掉 ──
CODEX_BLOCK='# 本项目的记忆统一存放在仓库内 .memory/，写入规则见 AGENTS.md。
#
# Codex 的记忆目录不可配置（固定为 $CODEX_HOME/memories），只能把它自带的记忆系统关掉：
#   generate_memories = false  本目录的交互会话不再沉淀到仓库外
#   use_memories      = false  不再注入 ~/.codex/memories 里的旧副本
#   dedicated_tools   = false  收掉 list/read/search/add_ad_hoc_note（最后一个是写工具，不关会绕过前两项）
#
# 生效前提：本项目须在 ~/.codex/config.toml 里被标记为 trusted，否则整个 .codex/ 静默不加载。
[memories]
generate_memories = false
use_memories = false
dedicated_tools = false'
mkdir -p .codex
if [ ! -f .codex/config.toml ]; then
    printf '%s\n' "$CODEX_BLOCK" > .codex/config.toml
    ok "已写 .codex/config.toml"
elif grep -q '^\[memories\]' .codex/config.toml; then
    if grep -qE '^generate_memories *= *false' .codex/config.toml \
        && grep -qE '^use_memories *= *false' .codex/config.toml \
        && grep -qE '^dedicated_tools *= *false' .codex/config.toml; then
        ok ".codex/config.toml 的 [memories] 三项已关"
    else
        warn ".codex/config.toml 已有 [memories] 节但三项未全为 false，未改动：请手工核对"
    fi
else
    printf '\n%s\n' "$CODEX_BLOCK" >> .codex/config.toml
    ok "已在 .codex/config.toml 追加 [memories] 节"
fi

# ── 6) AGENTS.md 写死记忆规则（仅 --with-rule）：没有全局规则时，这是 Codex / dsh / opencode 侧唯一的约束手段 ──
# Claude 的记忆格式与「先读索引」由它自己的系统提示注入，别的工具没有这一层，只能靠规则文件——全局的或仓内的。
if [ "$WRITE_RULE" -eq 0 ]; then
    ok "未传 --with-rule：不改 AGENTS.md（读写规则由全局规则仓承担）"
elif [ -f AGENTS.md ] && grep -q '\.memory/' AGENTS.md; then
    ok "AGENTS.md 已提及 .memory/，不重复追加"
elif [ -f AGENTS.md ] && [ ! -L AGENTS.md ]; then
    [ -n "$(tail -c1 AGENTS.md)" ] && echo >> AGENTS.md
    cat >> AGENTS.md <<'RULE'

## 项目记忆（所有 Agent 共用）

本项目的跨会话记忆一律存在仓内 `.memory/`，随代码提交；不使用各工具自带的仓外记忆。

- 会话开始先读 `.memory/MEMORY.md` 索引，命中再读对应条目；索引每条一行：`- [标题](文件.md) — 摘要`。
- 只记换个会话仍有用、且代码与 Git 历史读不出来的事：用户偏好、纠正过的做法、外部资源指针、非显然约束。不记代码结构、已修的 bug、本次会话的临时结论。
- 一条记忆一个 `.md`：frontmatter 含 `name`（短横线 slug）、`description`（一句话，供判断相关性）、`metadata.type`（`user` | `feedback` | `project` | `reference`）；正文一个事实，`feedback` / `project` 类附 **Why** 与 **How to apply**。
- 写入前先查已有条目：已覆盖就更新，不新建重复；发现错误的记忆直接删除。
RULE
    ok "已在 AGENTS.md 追加「项目记忆」节"
fi

# ── 7) worktree 共享钩子：git worktree add 后把根工作区的本机资产共享进新 worktree ──
# git worktree add 只检出入库文件，接线写下的本机文件（团队仓里的 CLAUDE.md / AGENTS.md、.codex/config.toml、项目级 skills、
# 未入库的 .memory）在新 worktree 里全部缺失。钩子装在仓库共用的 hooks 目录，任何方式建的 worktree（git、Claude --worktree、
# superpowers）都触发；模板见同目录 hooks/post-checkout，__SKILL_DIR__ 替换为本 skill 的绝对路径，Windows 上钩子按 $OSTYPE 分派到 .ps1。
# 管道运行时 SCRIPT_DIR 无意义，按全局安装的托管位置兜底。
SKILL_DIR="$SCRIPT_DIR"
[ -n "$SKILL_DIR" ] && [ -f "$SKILL_DIR/worktree-share.sh" ] || SKILL_DIR="$HOME/.vvnocode/rules/skills/agent-memory-setup"
HOOK_MARK='# agent-memory-setup post-checkout'
HOOK_HINT="bash \"$SKILL_DIR/worktree-share.sh\" link \"\$PWD\" || true"
if [ ! -f "$SKILL_DIR/worktree-share.sh" ]; then
    warn "未找到 $SKILL_DIR/worktree-share.sh，跳过钩子安装：请先运行全局安装（vvnocode/AGENTS.md 的 install.sh）再重跑"
elif [ -n "$(git config --get core.hooksPath || true)" ]; then
    warn "本仓已设 core.hooksPath=$(git config --get core.hooksPath)，.git/hooks 不生效，未写钩子：请在该目录 post-checkout 的 flag=1 分支末尾追加：$HOOK_HINT"
else
    HOOK="$(git rev-parse --git-path hooks)/post-checkout"
    mkdir -p "$(dirname "$HOOK")"
    if [ -f "$HOOK" ] && ! head -5 "$HOOK" | grep -qxF "$HOOK_MARK"; then
        warn "$HOOK 已存在且不是本 skill 写的，未覆盖：请在其 flag=1 分支末尾追加：$HOOK_HINT"
    else
        sed "s|__SKILL_DIR__|$SKILL_DIR|" "$SKILL_DIR/hooks/post-checkout" > "$HOOK"
        chmod +x "$HOOK"
        ok "已写 ${HOOK}（worktree 共享钩子）"
    fi
fi

# ── 8) 收尾：需要人工做的两件事 ──
echo
echo "── Codex 信任（用 Codex 才需要；项目未被信任时 .codex/ 整体静默不加载）──"
echo "把下面这段追加到 ~/.codex/config.toml："
echo
echo "[projects.\"$ROOT\"]"
echo "trust_level = \"trusted\""
echo
echo "── 验证 ──"
echo "Claude：在本目录开 Claude Code，问「不用工具，复述项目指令里关于记忆写入位置的那条」"
PROBE="$SCRIPT_DIR/codex-effective-config.py"
if [ -f "$PROBE" ]; then
    echo "Codex ：确认 trusted 后运行 $PROBE \"$ROOT\""
else
    echo "Codex ：确认 trusted 后运行 curl -fsSL $RAW_BASE/codex-effective-config.py | python3 - \"$ROOT\""
fi
echo "dsh / opencode：在本目录开会话，问同一问题；它们读 AGENTS.md，答得出即生效"
echo "worktree：新建的 worktree 由钩子自动共享本机资产（规则文件、.memory、项目级 skills、Codex 配置）；接线前已有的 worktree 手动执行一次："
echo "         bash \"$SKILL_DIR/worktree-share.sh\" link <worktree路径>（Windows：pwsh -File \"$SKILL_DIR/worktree-share.ps1\" link <worktree路径>）"
[ "$WARN" -gt 0 ] && echo && echo "⚠ 共 $WARN 条告警，见上文，需人工处理"
exit 0
