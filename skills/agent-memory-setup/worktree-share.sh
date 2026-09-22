#!/usr/bin/env bash
# worktree-share.sh：把根工作区里被 gitignore 排除的本机资产共享进附属 worktree。
#
#   worktree-share.sh link [worktree路径]    缺省为当前目录所在 worktree；对根工作区只提示不动作
#
# 背景：git worktree add 只检出入库文件。接线时写下的 CLAUDE.md / AGENTS.md（团队仓里常不入库）、.memory、
# 项目级 skills、.codex/config.toml 等在新 worktree 里全部缺失，会话因此丢规则、丢记忆。
#
# 共享规则：
# - 文件复制（内容静态、体积小，真实文件不受尾斜杠忽略规则影响）；目录软链（.memory 必须单一写入者，skills 只读）。
# - 只共享「根工作区有、未入库、已被忽略」的项；未入库也未忽略的视为待提交，只告警不共享。
# - 工具配置目录（.claude / .codex / .agents / .gemini / .opencode / .cursor）按整目录列入清单：整目录被忽略就整目录软链，
#   其下 commands、hooks、skills、settings 一并可见；目录含入库文件（如 .claude/skills 入库）或目录本身未被忽略（只有
#   其下某些项被忽略）时，展开为其下被忽略的条目逐条共享。repos/.gitkeep 入库、其下克隆被忽略的情形同理。
# - 清单项可带通配（.env.*）：在根工作区展开后逐项按上面规则处理。
# - .claude/settings.local.json 与 .claude/worktrees 在展开时静默跳过：前者 Claude Code 在 worktree 里直接读主工作区那份，
#   且含本机绝对路径，复制出去会分叉；后者是 Claude 自建 worktree 的容器。清单里显式写它们则告警。整目录软链 .claude 时两者
#   随目录可见，那是同一份文件，不会分叉。
# - 忽略规则带尾斜杠（如 .memory/）只匹配真实目录、不匹配软链：动作后用 check-ignore 复核，未被忽略就往仓库共用的
#   .git/info/exclude 补一行不带尾斜杠的路径（对所有 worktree 生效），不碰团队的 .gitignore。
#
# 清单 = 内置清单 + 仓根 .worktree-share：一行一项、# 注释、! 前缀剔除内置项；根工作区与目标 worktree 两份取并集，
# 分支里新增的项合入前就生效。类型不用声明，根工作区里是目录就链、是文件就复制。
#
# 不做持续同步：共享只在 link 时按根工作区当时的状态做一次。之后在 worktree 里新建的被忽略条目（软链目录之下的除外）、
# 对复制文件的改动都只留在 worktree；git worktree remove 不检查被忽略文件，不加 --force 也会连同删除。
# 删 worktree 前的列出与回收做法见 SKILL.md「worktree 里效果不变」。
#
# 由 setup.sh 安装的 post-checkout 钩子在 git worktree add 后自动调用本脚本 link；接线前建的 worktree 手动执行一次。
# link 末尾会调一次 memory-sync.sh，把 Codex 记忆里属于本仓的部分同步进主工作区的 .memory（无 .memory 时静默）。
# 兼容 macOS 自带 bash 3.2：不用 mapfile、关联数组、${var,,}。
set -euo pipefail

BUILTIN="CLAUDE.md AGENTS.md GEMINI.md .mcp.json opencode.json .env .env.* .memory .claude .codex .agents .gemini .opencode .cursor"
NEVER=".claude/settings.local.json .claude/worktrees"
CONF=".worktree-share"
EXCLUDE_MARK="# agent-memory-setup：worktree 共享项"
N_NEW=0; N_OK=0; N_WARN=0

usage() {
    sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}
warn() { echo "⚠ $*"; N_WARN=$((N_WARN + 1)); }

# 目录的真实路径（去软链；macOS 的 /tmp、/var 都是软链，比较路径前必须归一）
realpath_of() { (cd "$1" && pwd -P); }

# 主 worktree（根工作区）的真实路径：git worktree list 首行固定是主 worktree
main_worktree_of() {
    realpath_of "$(git -C "$1" worktree list --porcelain | head -1 | sed 's/^worktree //')"
}

# 读一份 .worktree-share：去注释、去空行、去行尾空白、去前导 ./ 与尾斜杠
read_conf() {
    [ -f "$1" ] || return 0
    grep -v '^[[:space:]]*#' "$1" | sed -e 's/[[:space:]]*$//' -e 's#^\./##' -e 's#/*$##' | grep -v '^$' || true
}

# 最终清单：内置 + 两份配置的并集，再剔除 ! 项；去重后按行输出
build_list() {
    local root=$1 wt=$2 line items removed=" "
    items=$(set -f; printf '%s\n' $BUILTIN)      # set -f：清单里的 .env.* 是给根工作区展开的，这里不能被当前目录展开
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
            !*) removed="$removed${line#!} " ;;
            *)  items="$items"$'\n'"$line" ;;
        esac
    done < <(read_conf "$root/$CONF"; read_conf "$wt/$CONF")
    printf '%s\n' "$items" | sort -u | while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$removed" in *" $line "*) continue ;; esac
        printf '%s\n' "$line"
    done
}

# 确保 worktree 里的 rel 被忽略；不被忽略就往共用的 info/exclude 补一行再复核
ensure_ignored() {
    local wt=$1 rel=$2 common exclude
    git -C "$wt" check-ignore -q -- "$rel" && return 0
    common=$(git -C "$wt" rev-parse --git-common-dir)
    case "$common" in /*) ;; *) common="$wt/$common" ;; esac
    exclude="$(realpath_of "$common")/info/exclude"
    mkdir -p "$(dirname "$exclude")"
    if ! grep -qxF "$EXCLUDE_MARK" "$exclude" 2>/dev/null; then
        [ -f "$exclude" ] && [ -s "$exclude" ] && [ -n "$(tail -c1 "$exclude")" ] && echo >> "$exclude"   # 补末尾换行
        printf '%s\n' "$EXCLUDE_MARK" >> "$exclude"
    fi
    printf '%s\n' "$rel" >> "$exclude"
    git -C "$wt" check-ignore -q -- "$rel"
}

# 共享一项：目录软链、文件复制；已就位计数；冲突告警不覆盖；动作后复核忽略
share_one() {
    local root=$1 wt=$2 rel=$3 src dst
    src="$root/$rel"; dst="$wt/$rel"
    if [ -L "$dst" ]; then
        if [ "$(readlink "$dst")" = "$src" ]; then N_OK=$((N_OK + 1)); else warn "$rel 已是软链但指向 $(readlink "$dst")，未覆盖"; fi
        return 0
    fi
    if [ -e "$dst" ]; then
        # 文件副本按内容相同判「已就位」；其余都是 worktree 自己的东西，不覆盖
        if [ -f "$dst" ] && [ -f "$src" ] && cmp -s "$src" "$dst"; then N_OK=$((N_OK + 1)); else warn "$rel 在 worktree 里已是真实文件/目录，未覆盖"; fi
        return 0
    fi
    mkdir -p "$(dirname "$dst")"
    if [ -d "$src" ]; then ln -s "$src" "$dst"; else cp -p "$src" "$dst"; fi
    if ! ensure_ignored "$wt" "$rel"; then
        rm -rf "$dst"
        warn "$rel 共享后仍未被忽略，已撤销：请检查忽略规则"
        return 0
    fi
    if [ -d "$src" ]; then echo "· 已链 $rel"; else echo "· 已复制 $rel"; fi
    N_NEW=$((N_NEW + 1))
}

is_never() { case " $NEVER " in *" $1 "*) return 0 ;; esac; return 1; }

# 展开一个目录：其下被忽略的条目（!! 行）逐条共享，NEVER 项静默跳过；未入库也未忽略的条目（?? 行）告警
share_children() {
    local root=$1 wt=$2 rel=$3 entry
    while IFS= read -r -d '' entry; do
        case "$entry" in
            '!! '*) entry=${entry#\!\! }; entry=${entry%/}; is_never "$entry" && continue; share_one "$root" "$wt" "$entry" ;;
            '?? '*) entry=${entry#\?\? }; entry=${entry%/}; warn "$entry 未入库也未忽略，视为待提交，不共享" ;;
        esac
    done < <(git -C "$root" status --ignored=matching --porcelain -z --untracked-files=normal -- "$rel")
}

# 处理清单里的一项：通配先在根工作区展开；目录整体被忽略就整目录软链，否则展开；文件按入库 / 忽略 / 待提交三分
share_item() {
    local root=$1 wt=$2 rel=$3 f
    case "$rel" in
        *\**|*\?*)
            while IFS= read -r f; do
                [ -n "$f" ] && share_item "$root" "$wt" "$f"
            done < <(cd "$root" && shopt -s nullglob dotglob && for f in $rel; do printf '%s\n' "$f"; done)
            return 0 ;;
    esac
    if is_never "$rel"; then
        warn "$rel 不共享：Claude Code 自身的本机状态（settings.local.json 由主工作区回读且含绝对路径；worktrees 是 Claude 自建 worktree 的容器）"
        return 0
    fi
    { [ -e "$root/$rel" ] || [ -L "$root/$rel" ]; } || return 0
    if [ -d "$root/$rel" ] && [ ! -L "$root/$rel" ]; then
        if [ -z "$(git -C "$root" ls-files -- "$rel" | head -1)" ] && git -C "$root" check-ignore -q -- "$rel"; then
            share_one "$root" "$wt" "$rel"          # 整目录未入库且被忽略：整目录软链
        else
            share_children "$root" "$wt" "$rel"     # 含入库文件，或目录本身未被忽略：展开其下被忽略的条目
        fi
        return 0
    fi
    [ -n "$(git -C "$root" ls-files -- "$rel" | head -1)" ] && return 0     # 入库文件：worktree 检出自带，不提
    if ! git -C "$root" check-ignore -q -- "$rel"; then
        warn "$rel 未入库也未忽略，视为待提交，不共享"
        return 0
    fi
    share_one "$root" "$wt" "$rel"
}

do_link() {
    local wt root rel
    wt=$(realpath_of "$1")
    root=$(main_worktree_of "$wt")
    if [ "$wt" = "$root" ]; then
        echo "· $wt 是根工作区，本机资产本就在此，无需链接"
        return 0
    fi
    echo "═══ worktree 共享：$root → $wt ═══"
    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        share_item "$root" "$wt" "$rel"
    done < <(build_list "$root" "$wt")
    echo "✓ 新建 ${N_NEW}，已就位 ${N_OK}，告警 ${N_WARN}"
    # 新 worktree 开会话前把 Codex 记忆同步到主工作区的 .memory（memory-sync.sh）；尽力而为，不影响本脚本退出码
    local sync_sh
    sync_sh="$(cd "$(dirname "$0")" && pwd -P)/memory-sync.sh"
    [ -f "$sync_sh" ] && { bash "$sync_sh" "$root" || true; }
    return 0
}

case "${1:-}" in
    link) [ $# -le 2 ] || usage; do_link "${2:-$PWD}" ;;
    *) usage ;;
esac
