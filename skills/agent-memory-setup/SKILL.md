---
name: agent-memory-setup
description: Use when a repo is worked on by more than one coding agent (Claude Code, Codex, dsh, opencode …) and their instructions or memory sit in separate places — AGENTS.md is present but Claude ignores it, agent memory lands in the home directory, switching tools loses accumulated context, setup.sh was run but one tool still ignores the shared instructions or memory, or a new machine needs the same setup reproduced in one step.
---

# 多 Agent 共用项目指令与仓内记忆

## 核心

一份指令、一份仓库内记忆，每个工具都指向它。做法是四件事：`AGENTS.md` 当正本、`CLAUDE.md` 只放一行 `@AGENTS.md` 引用；记忆放仓内 `.memory/` 随代码提交；能改记忆目录的工具用配置指过来，不能改的把自带记忆关掉；再把记忆读写规则写进 `AGENTS.md`。**各工具强度不对等**：Claude 可以用配置硬指定记忆目录；Codex 的记忆目录写死在 `$CODEX_HOME/memories`，只能关掉再靠指令约束；dsh 与 opencode 没有自带的跨会话记忆，全靠指令。

搭建本身由 `setup.sh` / `setup.ps1` 一次做完，脚本写下什么、为什么那样写见脚本各步骤的注释。本 skill 的主体是脚本之后的部分：怎么验证各工具真的生效、生效不了通常卡在哪。

## 机制对照

| | Claude Code | Codex | dsh | opencode |
|---|---|---|---|---|
| 读项目指令 | 只读 `CLAUDE.md`（**不读 `AGENTS.md`**） | 只读 `AGENTS.md` | `AGENTS.md`（也认 `CLAUDE.md`） | 只读 `AGENTS.md` |
| 自带跨会话记忆 | 有；目录可改：`autoMemoryDirectory` | 有；目录**不可改**，固定 `$CODEX_HOME/memories` | 无 | 无 |
| 记忆读写规则来源 | 自身系统提示 + `AGENTS.md` | 仅 `AGENTS.md` | 仅 `AGENTS.md` | 仅 `AGENTS.md` |
| 用户级指令 | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | `$DSH_HOME/AGENTS.md`（默认 `~/.dsh/`） | `~/.config/opencode/AGENTS.md` |
| 项目级配置 | `.claude/settings.local.json` | `.codex/config.toml`（**需项目被信任**） | 无 | 无需 |
| 全局 Skill 发现根 | `~/.claude/skills/` | `~/.codex/skills/` | `~/.agents/skills/` | `~/.config/opencode/skills/`、`~/.claude/skills/`、`~/.agents/skills/` |

「记忆读写规则来源」一行是关键：只有 Claude 自带「先读索引、按 frontmatter 写」的系统提示，其他三个工具只有规则文件里写了才会做。规则放在**用户级**最省事：一份跨工具规则仓软链到上表「用户级指令」四处，写一次「仓内 `.memory/` 存在时怎么读写」，所有仓库生效（参考 [vvnocode/AGENTS.md](https://github.com/vvnocode/AGENTS.md) 的「项目记忆」节）。没有全局规则的仓库才需要把规则写进仓内 `AGENTS.md`（`setup.sh --with-rule`）。

## 一键执行

macOS / Linux，在目标仓库根目录运行或传路径：

```bash
./setup.sh [仓库路径] [--with-rule]
```

Windows，系统自带的 PowerShell 5.1 即可：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\setup.ps1" [仓库路径] [-WithRule]
```

参数含义、不装 skill 直接用 curl / irm 执行的写法见同目录 README.md。跑完按输出做两件人工事：往 `~/.codex/config.toml` 追加信任片段（用 Codex 才需要），然后按下一节逐工具验证。脚本只告警不动的冲突要人工处理，最常见的是 `AGENTS.md` 与 `CLAUDE.md` 都是普通文件且内容不同：把 `CLAUDE.md` 并入 `AGENTS.md`，再把 `CLAUDE.md` 改为只含引用行。

## 验证

- Claude：在仓库目录开会话，问「不用工具，复述项目指令里关于记忆写入位置的那条」；答不出就是 `CLAUDE.md` 没加载。
- Codex：`./codex-effective-config.py <仓库绝对路径>`（Windows：`python codex-effective-config.py <路径>`）。它走 app-server 的 `config/read` 按 cwd 解析项目层，并抓 stderr 里的未信任警告。**不要用 `codex doctor`**，它只报全局值。
- dsh / opencode：开会话问同一问题，它们读 `AGENTS.md`。
- 记忆可见性：在 `MEMORY.md` 放一条带口令的索引行，问各工具读到几条。

## 陷阱

| 陷阱 | 后果 | 应对 |
|---|---|---|
| 没有 `CLAUDE.md` | Claude 完全不读项目规则，**无任何提示** | 必须有一行 `@AGENTS.md` |
| `CLAUDE.md` 是入库的软链 | Windows 检出后变成只含 `AGENTS.md` 的文本文件，Claude 读到的是这四个字 | 改为 `@AGENTS.md` 引用行，脚本会自动迁移 |
| Codex 项目未被信任 | `.codex/` 的 config、hooks、exec policies **整体**不加载（skills 仍加载），**静默失效**，只在 app-server 的 stderr 报一行 | `~/.codex/config.toml` 的 `[projects."<仓库绝对路径>"]` 下加 `trust_level = "trusted"`，脚本收尾按实际路径打印；仓库改路径要重做 |
| 拿 `codex doctor` 当证据 | 只报全局配置，得出反向结论 | 用 `codex-effective-config.py` |
| 只关 `generate_memories` | `add_ad_hoc_note` 仍往仓库外写 | `generate_memories`、`use_memories`、`dedicated_tools` 三项一起关 |
| **Codex 后台记忆管线只读全局配置** | 项目级 `generate_memories = false` **挡不住**它按会话更新时间重新提取、重建 `~/.codex/memories` | 要彻底停只能改全局，代价是所有项目一起停；否则接受仓库外持续产生副本，本项目 `use_memories = false` 读不回来即可 |
| 去清 `~/.codex/memories` | 数据流是 `memories_1.sqlite` 的 `stage1_outputs` → `raw_memories.md` → `MEMORY.md` 等五处，只删 `MEMORY.md` 无效；清了也会被重建 | 不要花时间清 |
| 在裸 worktree 里开 Claude 会话 | `settings.local.json` 缺失，记忆目录退回默认位置 | `git worktree add` 只检出入库文件，被 gitignore 的 `settings.local.json` 不会带过去：把根工作区的 `.claude/settings.local.json` 软链到 worktree 同路径，或用 post-checkout 钩子自动做 |
| 规则只写在 Claude 那侧 | Codex / dsh / opencode 不知道 `.memory/` 存在，各写各的或不写 | 不能省：全局规则或 `--with-rule` 二选一 |
| 全局规则只挂了部分工具 | 漏挂的工具（常见是 opencode 的 `~/.config/opencode/AGENTS.md`）永远读不到规则 | 按上表「用户级指令」四处逐一核对软链 |

## 常见错误

- 只做了 Claude 一侧，以为「别的工具本来就读 AGENTS.md 所以没问题」：它们读到的规则文件里根本没有记忆规则。
- 装了全局规则又每仓 `--with-rule`：两份同义规则并存，不出错但多余。
- 自己发明一个 `MEMORY.md` 约定但没设 `autoMemoryDirectory`：Claude 的自动记忆仍写在仓库外。
- 把 `autoMemoryDirectory` 写进入库的 `settings.json`：被忽略，且带上了本机绝对路径。
- 在未被信任的临时目录里测 Codex 项目配置，得出「项目级配置无效」的错误结论。

## 与 llm-wiki 的关系

[llm-wiki](https://github.com/vvnocode/llm-wiki)（个人知识工作台）v0.3.0 起的 `bootstrap.sh` / `bootstrap.ps1` 直接调用本 skill 的 setup 脚本完成接线（未装先装到三处发现根），自己只保留 worktree 共享钩子与 Skill 全局挂载等工作台特有步骤。两者分工：本 skill 管**接线**（一份指令、一份仓内记忆、各工具指过来），llm-wiki 管**知识**（跨项目的机制、决策、案例）。内容层面 `.memory/` 记做事方式（偏好、纠正、约束、指针），wiki 记事实结论（对象、机制、决策、案例），判据与机械规则见 llm-wiki 的 `docs/schemas/分区与共享.md`「与 `.memory/` 的分工」。
