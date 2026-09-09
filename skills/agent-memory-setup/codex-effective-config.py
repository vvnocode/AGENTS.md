#!/usr/bin/env python3
"""打印 Codex 从指定目录解析出的**有效** memories 配置。

为什么需要它：`codex doctor` 只报全局 config.toml 的值，看不出项目级 .codex/config.toml
是否被采纳，容易得出反向结论。这里走 app-server 的 JSON-RPC `config/read`，该接口按
cwd 解析项目配置层，是唯一可靠的判定方式。

同时抽取 stderr —— 项目未被信任时，Codex 只在这里报一行警告，配置会静默失效。

用法：
    ./codex-effective-config.py /path/to/repo
    ./codex-effective-config.py /path/to/repo --codex /custom/path/to/codex
"""
import json
import shutil
import subprocess
import sys
import threading

# 常见安装位置；也可用 --codex 显式指定
DEFAULT_CANDIDATES = [
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "codex",
]


def resolve_codex(argv: list[str]) -> str:
    if "--codex" in argv:
        return argv[argv.index("--codex") + 1]
    for c in DEFAULT_CANDIDATES:
        p = shutil.which(c) if not c.startswith("/") else (c if shutil.os.path.exists(c) else None)
        if p:
            return p
    sys.exit("找不到 codex 可执行文件，用 --codex <路径> 指定")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cwd = sys.argv[1]
    codex = resolve_codex(sys.argv)

    proc = subprocess.Popen(
        [codex, "app-server"],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    # stderr 必须单独抽干：既要看信任警告，也避免管道写满阻塞子进程
    errs: list[str] = []
    threading.Thread(target=lambda: errs.extend(proc.stderr), daemon=True).start()

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"clientInfo": {"name": "probe", "title": "probe", "version": "0.0.1"}}})
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send({"jsonrpc": "2.0", "id": 2, "method": "config/read",
          "params": {"cwd": cwd, "includeLayers": True}})

    cfg = None
    for _ in range(40):
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            cfg = msg.get("result", {}).get("config")
            break
    proc.kill()

    trust_warning = any("until the project is trusted" in e for e in errs)
    if trust_warning:
        print("!! 该目录未被信任：项目级 .codex/ 的 config、hooks、exec policies 全部未加载")
        print("   在 ~/.codex/config.toml 加：")
        print(f'   [projects."{cwd}"]\n   trust_level = "trusted"\n')

    if cfg is None:
        print("未取到有效配置。stderr 前几行：")
        print("".join(errs[:10]))
        sys.exit(1)

    mem = {k: v for k, v in (cfg.get("memories") or {}).items() if v is not None}
    print(f"cwd              : {cwd}")
    print(f"model            : {cfg.get('model')}")
    print(f"memories 有效值  : {json.dumps(mem, ensure_ascii=False)}")
    print()
    want = {"generate_memories": False, "use_memories": False, "dedicated_tools": False}
    bad = {k: mem.get(k) for k, v in want.items() if mem.get(k) is not v}
    if bad:
        print(f"×  未达预期（应三项皆为 false）：{json.dumps(bad, ensure_ascii=False)}")
    else:
        print("√  Codex 自带记忆系统在该目录下已完全关闭")
    print("\n注意：这只覆盖以该目录为 cwd 的交互会话。后台记忆管线读的是全局")
    print("~/.codex/config.toml，不受此处影响，仍可能在仓库外重新生成副本。")


if __name__ == "__main__":
    main()
