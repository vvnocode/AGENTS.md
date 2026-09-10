#!/usr/bin/env bash
# memory-sync.sh：memory-sync.py 的薄包装（macOS / Linux）。找 python3，转调，透传退出码。
# 用法：memory-sync.sh [仓库路径]    行为与输出契约见 memory-sync.py 文件头。
set -u
HERE=$(cd "$(dirname "$0")" && pwd -P)
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
    echo "⚠ memory-sync：需要 python3" >&2
    exit 0    # 钩子里调用，不能影响会话
fi
exec "$PY" "$HERE/memory-sync.py" "$@"
