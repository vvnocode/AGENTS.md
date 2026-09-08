#!/usr/bin/env bash
# 把本仓的 CLAUDE.md 软链到本机各 AI 编码工具的用户级规则入口。幂等、只增不减、不覆盖已有文件。
#
# 用法（不需要手工 clone）：
#   curl -fsSL https://raw.githubusercontent.com/vvnocode/claude.md/main/install.sh | bash
#   ./install.sh                                   # 在本仓 clone 内运行：软链指向本仓，开发用
#
# 仓库来源按运行位置自动判定：
#   仓外 / 管道运行：把仓库 clone 到 $RULES_REPO_DIR（缺省 ~/.vvnocode/rules，与 skills 仓 ~/.vvnocode/skills 同一约定），
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
set -euo pipefail

# 整个脚本体包进 main：curl | bash 时 bash 边读边执行，包成函数后必须读完整个脚本才开始执行，下载中断不会执行半截脚本。
# 注意：变量后紧跟中文标点必须写 ${VAR}。macOS 自带 bash 3.2 在 UTF-8 locale 下会把 $VAR（ 的首字节并入变量名。
main() {

    REPO_URL="${RULES_REPO_URL:-https://github.com/vvnocode/claude.md.git}"
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
    # $0 所在目录同时有 install.sh 与 CLAUDE.md 即视为本仓 clone；管道运行时 $0 是 bash，落到托管副本分支。
    HERE=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P || true)
    if [ -n "$HERE" ] && [ -f "$HERE/install.sh" ] && [ -f "$HERE/CLAUDE.md" ]; then
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
    RULES="$REPO/CLAUDE.md"

    # ── 软链到各工具入口 ──
    for link in "${ENTRIES[@]}"; do
        mkdir -p "$(dirname "$link")"
        if [ -L "$link" ]; then
            # 已是软链：指向本仓即就位；指向旧托管位置的是按早期 README 建的，重指到新位置；指向别处只告警（可能是用户自己的规则仓）
            cur=$(readlink "$link")
            if [ "$cur" = "$RULES" ]; then
                KEPT=$((KEPT+1))
            elif [ "${cur#"$LEGACY_DIR/"}" != "$cur" ]; then
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
    echo "· 安装完成：新建 $ADDED 条，已就位 $KEPT 条，重指 $MOVED 条，告警 $WARN 条（规则源：${RULES}）"
    echo "· Cursor 的全局 User Rules 需在设置界面手工粘贴规则正文"
}

main "$@"
