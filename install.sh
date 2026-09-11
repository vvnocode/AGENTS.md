#!/usr/bin/env bash
# 把本仓的 AGENTS.md 软链到本机各 AI 编码工具的用户级规则入口。幂等、只增不减、不覆盖已有文件。
#
# 用法（不需要手工 clone）：
#   curl -fsSL https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/install.sh | bash
#   ./install.sh                                   # 在本仓 clone 内运行：软链指向本仓，开发用
#
# 仓库来源按运行位置自动判定：
#   仓外 / 管道运行：把仓库 clone 到 $RULES_REPO_DIR（缺省 ~/.vvnocode/rules），
#                    已存在则 git pull --ff-only；重跑同一条命令即更新，软链不用重做。RULES_REPO_URL 可改为 fork 地址。
#                    README 早期写法把仓库放在 ${XDG_CONFIG_HOME:-~/.config}/vibe-coding-rules：新位置不存在而旧位置有副本时
#                    自动搬过去，指向旧位置的入口链接重指到新位置。
#   本仓 clone 内  ：直接用所在 clone，不联网、不建托管副本。
# 入口已是普通文件（多半是用户自己的规则）或指向别处的链接：只告警不覆盖，请先把自己的规则并入，再手动换成链接。
#
# 挂载的入口（各工具官方约定，见 README 支持矩阵）：
#   ~/.claude/CLAUDE.md                                Claude Code
#   ~/.codex/AGENTS.md                                 Codex
#   ~/.gemini/GEMINI.md                                Gemini CLI
#   ${XDG_CONFIG_HOME:-~/.config}/opencode/AGENTS.md   OpenCode
#   ${DSH_HOME:-~/.dsh}/AGENTS.md                      DeepSeek Harness
# Cursor 的全局 User Rules 只能在设置界面粘贴，不在此列。
#
# 同时把本仓 skills/agent-memory-setup（单仓接线：一份指令、一份仓内记忆、worktree 共享钩子）软链到三处全局 Skill 发现根：
#   ~/.agents/skills、~/.claude/skills、~/.codex/skills
#   再向 ~/.claude/settings.json 与 ~/.codex/hooks.json 各追加一条 SessionStart 钩子（memory-sync），RULES_NO_HOOKS=1 跳过；
#   ~/.codex/config.toml 里弃用的 [features] codex_hooks 改名为 hooks（值不变），hooks = false 只告警
set -euo pipefail

# 整个脚本体包进 main：curl | bash 时 bash 边读边执行，包成函数后必须读完整个脚本才开始执行，下载中断不会执行半截脚本。
# 注意：变量后紧跟中文标点必须写 ${VAR}。macOS 自带 bash 3.2 在 UTF-8 locale 下会把 $VAR（ 的首字节并入变量名。
main() {

    REPO_URL="${RULES_REPO_URL:-https://github.com/vvnocode/AGENTS.md.git}"
    REPO_DIR="${RULES_REPO_DIR:-$HOME/.vvnocode/rules}"
    LEGACY_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-coding-rules"   # README 早期写法的位置，见下方迁移
    ENTRIES=(
        "$HOME/.claude/CLAUDE.md"
        "$HOME/.codex/AGENTS.md"
        "$HOME/.gemini/GEMINI.md"
        "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/AGENTS.md"
        "${DSH_HOME:-$HOME/.dsh}/AGENTS.md"
    )
    ADDED=0; KEPT=0; MOVED=0; WARN=0

    # ── 仓库来源 ──
    # $0 所在目录同时有 install.sh 与 AGENTS.md 即视为本仓 clone；管道运行时 $0 是 bash，落到托管副本分支。
    HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P || true)
    if [ -n "$HERE" ] && [ -f "$HERE/install.sh" ] && [ -f "$HERE/AGENTS.md" ]; then
        REPO="$HERE"
        echo "· 来源：本仓 clone $REPO"
    else
        command -v git >/dev/null || { echo "✗ 需要 git"; exit 1; }
        # 旧位置迁移：只在用默认位置、新位置尚不存在、旧位置确是 git 仓库时搬；显式传了 RULES_REPO_DIR 不动旧目录
        if [ -z "${RULES_REPO_DIR:-}" ] && [ ! -e "$REPO_DIR" ] && [ -d "$LEGACY_DIR/.git" ]; then
            mkdir -p "$(dirname "$REPO_DIR")"
            mv "$LEGACY_DIR" "$REPO_DIR"
            echo "· 托管副本已从 $LEGACY_DIR 搬到 ${REPO_DIR}，指向旧位置的入口链接将重指"
        fi
        if [ -d "$REPO_DIR/.git" ]; then
            # 已有托管副本：快进更新；拉不动（本地改动、断网）就沿用现有版本，不中断安装
            if git -C "$REPO_DIR" pull -q --ff-only; then
                echo "· 来源：托管副本 ${REPO_DIR}（已更新）"
            else
                echo "⚠ $REPO_DIR 更新失败，沿用现有版本（本地有改动或网络不通）"; WARN=$((WARN+1))
            fi
        elif [ -e "$REPO_DIR" ]; then
            echo "✗ $REPO_DIR 已存在但不是 git 仓库，请移走后重试"; exit 1
        else
            mkdir -p "$(dirname "$REPO_DIR")"
            git clone -q "$REPO_URL" "$REPO_DIR"
            echo "· 来源：已 clone $REPO_URL 到 $REPO_DIR"
        fi
        REPO=$(cd "$REPO_DIR" && pwd -P)
    fi
    RULES="$REPO/AGENTS.md"

    # ── 软链到各工具入口 ──
    for link in "${ENTRIES[@]}"; do
        mkdir -p "$(dirname "$link")"
        if [ -L "$link" ]; then
            # 已是软链：指向本仓即就位；指向旧托管位置（早期 README）或本仓旧文件名 CLAUDE.md（2026-09-08 改名前）的重指；
            # 指向别处只告警（可能是用户自己的规则仓）
            cur=$(readlink "$link")
            if [ "$cur" = "$RULES" ]; then
                KEPT=$((KEPT+1))
            elif [ "${cur#"$LEGACY_DIR/"}" != "$cur" ] || [ "$cur" = "$REPO/CLAUDE.md" ]; then
                rm "$link"; ln -s "$RULES" "$link"; MOVED=$((MOVED+1))
            else
                echo "⚠ $link 已指向 ${cur}，未改动"; WARN=$((WARN+1))
            fi
        elif [ -e "$link" ]; then
            echo "⚠ $link 已是普通文件，未改动：请把其中你自己的规则并入后再换成链接（ln -sf \"$RULES\" \"$link\"）"; WARN=$((WARN+1))
        else
            ln -s "$RULES" "$link"; ADDED=$((ADDED+1))
        fi
    done
    # ── 软链 skill 到三处全局 Skill 发现根 ──
    # ~/.agents/skills 是跨工具约定俗成位（dsh、opencode、Cline 等直接读）；Claude 与 Codex 只认自己的目录、不扫它，三处缺一不可。
    # agent-memory-setup 原在 vvnocode/skills 仓，2026-09-08 并入本仓：指向旧托管位置（~/.vvnocode/skills）
    # 或更早的 XDG 位置（vvnocode-skills）的链接重指到本仓；指向别处的只告警。
    SKILL_SRC="$REPO/skills/agent-memory-setup"
    OLD_SKILL_1="$HOME/.vvnocode/skills/skills/agent-memory-setup"
    OLD_SKILL_2="${XDG_DATA_HOME:-$HOME/.local/share}/vvnocode-skills/skills/agent-memory-setup"
    S_ADDED=0; S_KEPT=0; S_MOVED=0
    for root in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
        link="$root/agent-memory-setup"
        mkdir -p "$root"
        if [ -L "$link" ]; then
            cur=$(readlink "$link")
            if [ "$cur" = "$SKILL_SRC" ]; then
                S_KEPT=$((S_KEPT+1))
            elif [ "$cur" = "$OLD_SKILL_1" ] || [ "$cur" = "$OLD_SKILL_2" ]; then
                rm "$link"; ln -s "$SKILL_SRC" "$link"; S_MOVED=$((S_MOVED+1))
            else
                echo "⚠ $link 已指向 ${cur}，未改动"; WARN=$((WARN+1))
            fi
        elif [ -e "$link" ]; then
            echo "⚠ $link 已是普通目录，未改动：请确认后手动换成链接（ln -sfn \"$SKILL_SRC\" \"$link\"）"; WARN=$((WARN+1))
        else
            ln -s "$SKILL_SRC" "$link"; S_ADDED=$((S_ADDED+1))
        fi
    done
    # ── 全局钩子：会话开始把 Codex 记忆同步进当前仓库的 .memory ──
    # Claude Code 与 Codex 都有 SessionStart 事件、都以会话目录为 cwd 运行 command 钩子，所以命令不带参数，脚本按 cwd 找仓库。
    # 命令走 ~/.agents/skills 的稳定路径（$HOME 在安装时展开，Codex 的信任提示里显示的就是最终命令）。
    # 只追加自己的条目（识别子串 agent-memory-setup 与 memory-sync），已有则跳过，其余内容原样保留；JSON 坏了只告警不动。
    # 未接线的仓库里脚本因无 .memory 静默退出，所以全局装一次即可。RULES_NO_HOOKS=1 跳过本段。
    HOOK_CMD="bash \"$HOME/.agents/skills/agent-memory-setup/memory-sync.sh\" || true"
    if [ "${RULES_NO_HOOKS:-0}" = "1" ]; then
        echo "· RULES_NO_HOOKS=1：跳过全局钩子"
    elif command -v python3 >/dev/null; then
        for spec in "$HOME/.claude/settings.json|SessionStart" "$HOME/.codex/hooks.json|SessionStart"; do
            file=${spec%%|*}; event=${spec##*|}
            echo "· 向 $file 的 hooks.$event 追加：$HOOK_CMD"
            python3 - "$file" "$event" "$HOOK_CMD" <<'PY' || { echo "⚠ $file 不是合法 JSON，未改动"; WARN=$((WARN+1)); }
import json, pathlib, sys
path, event, cmd = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = {}
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8") or "{}")   # 解析失败抛异常 → 非零退出 → shell 侧告警
hooks = data.setdefault("hooks", {})
groups = hooks.setdefault(event, [])
if any("agent-memory-setup" in h.get("command", "") and "memory-sync" in h.get("command", "")
       for g in groups for h in g.get("hooks", [])):
    print(f"· {path} 已有 memory-sync 钩子")
    sys.exit(0)
groups.append({"hooks": [{"type": "command", "command": cmd}]})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"· 已写 {path}（hooks.{event}）")
PY
        done
        # Codex 钩子默认开启（[features] hooks），旧名 codex_hooks 已弃用但仍被接受：把弃用名改成正名、保留原值，其余字节不动；
        # 明确写了 hooks = false 的只告警（memory-sync 钩子不会跑），不代开；没有 config.toml 或没有 [features] 节不补写。
        # 退出码：0 无事，2 hooks = false，其余为读写失败。
        rc=0
        python3 - "$HOME/.codex/config.toml" <<'PY' || rc=$?
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
if not path.is_file():
    sys.exit(0)
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
HEADER = re.compile(r"\s*\[features\]\s*(#.*)?$")
in_features, has_hooks = False, False
for line in lines:                                   # 先看 [features] 里有没有正名，决定弃用行是改名还是删除
    if re.match(r"\s*\[", line):
        in_features = bool(HEADER.match(line.rstrip("\r\n")))
    elif in_features and re.match(r"\s*hooks\s*=", line):
        has_hooks = True
out, in_features, changed, hooks_value = [], False, False, None
for line in lines:
    if re.match(r"\s*\[", line):
        in_features = bool(HEADER.match(line.rstrip("\r\n")))
    elif in_features:
        m = re.match(r"(\s*)codex_hooks(\s*=[^\r\n]*)(\r?\n?)$", line)
        if m:
            changed = True
            if has_hooks:
                continue                             # 正名已在：弃用行直接删
            line = f"{m.group(1)}hooks{m.group(2)}{m.group(3)}"   # 改名，值与行尾原样保留
        if re.match(r"\s*hooks\s*=", line):
            hooks_value = line.split("=", 1)[1].split("#", 1)[0].strip()
    out.append(line)
if changed:
    path.write_text("".join(out), encoding="utf-8")
    print(f"· {path} 的 [features] codex_hooks 已改为 hooks（Codex 已弃用旧名，值不变）")
sys.exit(2 if hooks_value == "false" else 0)
PY
        case $rc in
            0) ;;
            2) echo "⚠ ~/.codex/config.toml 的 [features] hooks = false：Codex 不加载任何钩子，memory-sync 不会执行（默认开启，去掉该行即可）"; WARN=$((WARN+1)) ;;
            *) echo "⚠ 读写 ~/.codex/config.toml 失败，未改动"; WARN=$((WARN+1)) ;;
        esac
        echo "· Codex 每条钩子都要人工信任：首次启动按提示在 Codex 里执行 /hooks 审核并信任这条定义（信任按定义哈希记在 ~/.codex/config.toml 的 [hooks.state]，命令改了要重新信任）；之后 codex exec \"ok\" 打印 hook: SessionStart 即生效"
    else
        echo "⚠ 未找到 python3，未写全局钩子；装好后重跑安装"; WARN=$((WARN+1))
    fi
    echo "· 安装完成：规则 新建 $ADDED 条，已就位 $KEPT 条，重指 $MOVED 条；skill 新建 $S_ADDED 条，已就位 $S_KEPT 条，重指 $S_MOVED 条；告警 $WARN 条（规则源：${RULES}）"
    [ -d "$HOME/.vvnocode/skills" ] && echo "· 旧 skills 仓托管副本 $HOME/.vvnocode/skills 已无用，可手动删除"
    echo "· 接线一个仓库：$SKILL_SRC/setup.sh [仓库路径]（Windows 用同目录 setup.ps1）"
    echo "· Cursor 的全局 User Rules 需在设置界面手工粘贴规则正文"
}

main "$@"
