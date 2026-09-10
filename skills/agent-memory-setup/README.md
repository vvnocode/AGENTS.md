# agent-memory-setup

让 Claude Code、Codex、dsh、opencode 在同一仓库共用一份指令（`AGENTS.md`，`CLAUDE.md` 只含一行 `@AGENTS.md` 引用）与一份仓内记忆（`.memory/`），换工具、换机器不丢上下文。机制对照、验证与陷阱见 [SKILL.md](SKILL.md)。

## 一键搭建

不需要 clone 本仓，在目标仓库目录下执行：

```bash
curl -fsSL https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.sh | bash
```

参数跟在 `bash -s --` 之后：

```bash
curl -fsSL https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.sh | bash -s -- /path/to/repo --with-rule
```

| 参数 | 含义 |
|---|---|
| `仓库路径` | 缺省为当前所在 git 仓库根 |
| `--with-rule` | 往 `AGENTS.md` 追加「项目记忆」节。装了跨工具全局规则（如 [vvnocode/AGENTS.md](https://github.com/vvnocode/AGENTS.md) 的「项目记忆」节）的机器不需要；只给没有全局规则的协作者用的仓库才加 |

幂等：只补缺不覆盖；不能自动裁定的冲突只告警交人工。跑完按输出做两件人工事：往 `~/.codex/config.toml` 追加信任片段（用 Codex 才需要），再逐工具验证。Codex 自带记忆不关闭，属于本仓的部分由 `memory-sync` 同步为 `.memory/` 下与 Claude 自动记忆同形的条目；首次可手动跑一次立即同步已有记忆：

```bash
~/.agents/skills/agent-memory-setup/memory-sync.sh [仓库路径]
```

Windows：`pwsh -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\memory-sync.ps1" [仓库路径]`。之后由全局安装写下的 Claude 与 Codex `SessionStart` 钩子自动触发；机制与不做的事见 [SKILL.md](SKILL.md)「工具记忆同步」。

已用根目录 `install.sh` 装好本 skill 的机器，也可直接运行本地副本：

```bash
~/.agents/skills/agent-memory-setup/setup.sh [仓库路径] [--with-rule]
```

## Windows

系统自带的 Windows PowerShell 5.1 即可，在目标仓库目录下执行：

```powershell
irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.ps1 | iex
```

带参数：

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/setup.ps1))) C:\path\to\repo -WithRule
```

已用根目录 `install.ps1` 装好本 skill 的机器，也可直接运行本地副本：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\setup.ps1" [仓库路径] [-WithRule]
```

两个脚本写入仓库的文件逐字节一致；脚本提示为英文（原因见根 README 的 Windows 说明）。旧 Windows 上 `irm` 报「基础连接已经关闭」时，先执行 `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072` 打开 TLS 1.2。

## worktree 共享

setup 装的 `post-checkout` 钩子让之后建的每个 worktree 自动带上根工作区被忽略的本机资产（规则文件、`.memory`、`.claude` / `.codex` / `.agents` / `.gemini` / `.opencode` / `.cursor` 整目录或其下被忽略的项、`.mcp.json`、`opencode.json`、`.env` 与 `.env.*`）。接线前建的 worktree 手动跑一次：

```bash
~/.agents/skills/agent-memory-setup/worktree-share.sh link /path/to/worktree
```

Windows：

```powershell
pwsh -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\worktree-share.ps1" link C:\path\to\worktree
```

仓根放 `.worktree-share` 增删共享项（一行一项，`#` 注释，`!` 前缀剔除内置项）。机制与陷阱见 [SKILL.md](SKILL.md)「worktree 里效果不变」。

## 验证 Codex 有效配置

`codex doctor` 只报全局配置，看不出项目级 `.codex/config.toml` 是否被采纳。探针走 app-server 的 `config/read` 按目录解析有效值，并抓「项目未被信任」的警告：

```bash
curl -fsSL https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/skills/agent-memory-setup/codex-effective-config.py | python3 - /path/to/repo
```

需要本机有 `codex` 可执行文件；不在 PATH 时追加 `--codex /path/to/codex`。Windows 上先把文件存下来再跑：`irm <同一地址> -OutFile "$env:TEMP\codex-effective-config.py"; python "$env:TEMP\codex-effective-config.py" C:\path\to\repo`。
