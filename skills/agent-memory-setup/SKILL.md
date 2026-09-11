---
name: agent-memory-setup
description: Use when a repo is worked on by more than one coding agent (Claude Code, Codex, dsh, opencode …) and their instructions or memory sit in separate places — AGENTS.md is present but Claude ignores it, agent memory lands in the home directory, switching tools loses accumulated context, setup.sh was run but one tool still ignores the shared instructions or memory, or a new machine needs the same setup reproduced in one step.
---

# 多 Agent 共用项目指令与仓内记忆

## 核心

一份指令、一份仓库内记忆，每个工具都指向它。做法是四件事：`AGENTS.md` 当正本、`CLAUDE.md` 只放一行 `@AGENTS.md` 引用；记忆放仓内 `.memory/` 随代码提交；能改记忆目录的工具用配置指过来，不能改的让它照常写、再由 `memory-sync` 按 cwd 把属于本仓的部分同步回来；再把记忆读写规则写进 `AGENTS.md`。**各工具强度不对等**：Claude 可以用配置硬指定记忆目录；Codex 的记忆目录写死在 `$CODEX_HOME/memories`，照常开启，属于本仓的部分同步为 `.memory/` 下的普通条目（见「工具记忆同步」），它自己往 `.memory/` 写则靠指令约束；dsh 与 opencode 没有自带的跨会话记忆，全靠指令。

搭建本身由 `setup.sh` / `setup.ps1` 一次做完，脚本写下什么、为什么那样写见脚本各步骤的注释；它顺带装一个 post-checkout 钩子，让之后建的每个 worktree 与根工作区效果一致（见「worktree 里效果不变」）。本 skill 的主体是脚本之后的部分：怎么验证各工具真的生效、生效不了通常卡在哪。

## 机制对照

| | Claude Code | Codex | dsh | opencode |
|---|---|---|---|---|
| 读项目指令 | 只读 `CLAUDE.md`（**不读 `AGENTS.md`**） | 只读 `AGENTS.md` | `AGENTS.md`（也认 `CLAUDE.md`） | 只读 `AGENTS.md` |
| 自带跨会话记忆 | 有；目录可改：`autoMemoryDirectory` | 有；目录**不可改**，固定 `$CODEX_HOME/memories`，由 `memory-sync` 按 cwd 同步为仓内 `.memory/` 普通条目 | 无 | 无 |
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
- Codex 记忆同步：`memory-sync.sh <仓根>`（Windows：`memory-sync.ps1`）后 `ls .memory/codex-*.md`，`MEMORY.md` 末尾出现 `<!-- codex-sync:begin -->` 段。无输出、无文件多半是 Codex 还没生成，见陷阱表。
- 全局钩子：Codex 里 `/hooks` 应列出 memory-sync 且已信任；`codex exec "ok"` 启动时逐行打印 `hook: <事件>`，出现 `hook: SessionStart` 与 `Completed` 即生效（未信任的钩子不出现在这些行里）。Claude Code：`/hooks` 在 User Settings 下列出该条，`claude --debug` 的日志 `~/.claude/debug/latest` 记 `hook_execution_start`。

## 陷阱

| 陷阱 | 后果 | 应对 |
|---|---|---|
| 没有 `CLAUDE.md` | Claude 完全不读项目规则，**无任何提示** | 必须有一行 `@AGENTS.md` |
| `CLAUDE.md` 是入库的软链 | Windows 检出后变成只含 `AGENTS.md` 的文本文件，Claude 读到的是这四个字 | 改为 `@AGENTS.md` 引用行，脚本会自动迁移 |
| Codex 项目未被信任 | `.codex/` 的 config、hooks、exec policies **整体**不加载（skills 仍加载），**静默失效**，只在 app-server 的 stderr 报一行 | `~/.codex/config.toml` 的 `[projects."<仓库绝对路径>"]` 下加 `trust_level = "trusted"`，脚本收尾按实际路径打印；仓库改路径要重做 |
| 拿 `codex doctor` 当证据 | 只报全局配置，得出反向结论 | 用 `codex-effective-config.py` |
| 刚说完就去查 `.memory/codex-*.md` | Codex 记忆是后台异步生成：会话空闲数小时后才总结，配额低于门限还会跳过；同步只能搬已生成的 | 先看 `~/.codex/memories/rollout_summaries/` 有没有本会话的文件：没有就是 Codex 还没生成，不是同步问题 |
| 手改 `codex-*.md` 或它的索引行 | 文件名是句子哈希、索引段每次整段重生成：改过的文件成孤儿，索引行被覆盖 | 要修正就删掉该文件另写一条正常记忆；索引段之外的行不会被动 |
| Codex 钩子未信任 | 新加或改过的钩子定义在 `/hooks` 信任前**静默**不执行，`codex exec` 的 `hook:` 行里没有它 | 启动 Codex 按提示打开 `/hooks` 审核并信任；信任按定义哈希记在全局 `config.toml` 的 `[hooks.state]`，命令变了要重新信任 |
| 全局 `[features] hooks = false` | Codex 不加载任何钩子 | 钩子默认开启，去掉该行；install 只告警不代开。旧名 `codex_hooks` 已弃用，install 会改成 `hooks` 并保留原值 |
| Codex Memories 没开 | 全局 `[features] memories = true` 缺失（默认关，EEA / 英国 / 瑞士不可用），`~/.codex/memories` 为空，同步永远无内容 | setup 收尾会提示；在全局 `config.toml` 或 App 设置里开，脚本不代开 |
| 接线前建的 worktree | 没经过钩子，根工作区未入库的规则文件、`.memory`、项目级 skills、`.codex/config.toml` 都不在 | `git worktree add` 只检出入库文件：手动执行一次 `worktree-share.sh link <worktree路径>`（Windows 用 `.ps1`），见下节 |
| 仓库设了 `core.hooksPath` 或已有别人的 `post-checkout` | setup 不覆盖，钩子没装，新 worktree 不共享 | 按 setup 输出的接入指引，在那份钩子的 flag=1 分支末尾追加一行调用 `worktree-share.sh` |
| 团队仓里接线文件未入库也未忽略（`git status` 里是 `??`） | 脚本视为待提交、不共享，只告警 | 要么提交，要么写进仓库本地的 `.git/info/exclude`（不碰团队 `.gitignore`）再建 worktree |
| Windows 没开开发者模式、也不是管理员 | 建不了目录符号链接：`.memory`、skills 目录不共享，脚本逐项告警；`.claude` 等工具配置目录退回到只复制其下的文件（如 `.codex/config.toml`），子目录仍不共享 | 设置 → 开发者选项 → 开发者模式，或提权后重跑共享脚本。不要手工建目录联接顶上：git 2.37.3 实测 `git worktree remove` 会穿过联接删掉根工作区的内容；符号链接则安全（`git worktree remove`、`rm -rf`、`rmdir /s` 都只删链接） |
| 规则只写在 Claude 那侧 | Codex / dsh / opencode 不知道 `.memory/` 存在，各写各的或不写 | 不能省：全局规则或 `--with-rule` 二选一 |
| 全局规则只挂了部分工具 | 漏挂的工具（常见是 opencode 的 `~/.config/opencode/AGENTS.md`）永远读不到规则 | 按上表「用户级指令」四处逐一核对软链 |

## 工具记忆同步

有自带记忆的工具照常写它的默认位置，不关闭；`memory-sync` 把其中属于本仓库的部分同步成 `.memory/` 下与 Claude 自动记忆**同形**的条目，任何只会读 `.memory/` 的 Agent 不必知道 Codex 的存在。目前只有 Codex 需要同步：Claude 已由 `autoMemoryDirectory` 直接写进项目，dsh 与 opencode 没有自带记忆。

- **来源与归属**：`$CODEX_HOME/memories/raw_memories.md`（按线程分块）与 `rollout_summaries/*.md`（按会话一文件），每条带 `cwd`；`cwd` 等于仓根、等于该仓任一现存 worktree、或位于 `<仓根>/.worktrees/`、`<仓根>/.claude/worktrees/` 之下的算本仓。
- **粒度与格式**：Codex 的每个列表项就是一条记忆，一条一文件平铺在 `.memory/` 根下，frontmatter 只有 `name`、`description`、`metadata.type`（Preference signals 与 Failures → `feedback`，Reusable knowledge → `project`）加溯源字段 `source: codex`、`thread_id`、`observed_at`；正文是 Codex 原句加一行来源。`References` 与 `rollout_path` 丢弃。
- **文件名** `codex-<task_group>-<hash10>.md`，`hash10` 是句子归一后的 sha256 前 10 位：同一句子跨来源、跨线程只一条，Codex 重排列表项不产生重复文件，已存在的文件不重写；线程有 raw 块时它的会话摘要整份不取（raw 块是 Codex 对同一 rollout 做的记忆提取，摘要是叙事复述，换个说法的同一事实按句子去重抓不到），没有 raw 块的线程才用摘要；分组名按线程统一。不删除来源已消失的条目。
- **索引**：`MEMORY.md` 末尾 `<!-- codex-sync:begin -->` / `<!-- codex-sync:end -->` 之间每条一行，与普通索引行同形，按日期倒序，封顶 60 行（Claude 开局只读索引前 200 行，用户自己的条目排前面）；段外内容一字不动。
- **掩码**：私钥块、`ghp_` / `glpat-` / `sk-` 前缀 token、`password|token|secret = …` 赋值形态替换为 `[已掩码]`，stderr 计数。Codex 自己会脱敏，这是入库前的第二道闸。
- **触发**：全局安装写 Claude 与 Codex 的 `SessionStart` 钩子（`RULES_NO_HOOKS=1` 跳过），命令不带参数、按会话 cwd 找仓库，没有 `.memory/` 静默退出；`worktree-share.sh link` 末尾也调一次；手动 `memory-sync.sh [仓根]`。Codex 钩子默认开启（`[features] hooks`；旧名 `codex_hooks` 已弃用，install 改成正名并保留原值，写了 `false` 的只告警），但每条非托管钩子都要人工信任：首次启动 Codex 会提示打开 `/hooks`，在里面审核并信任这条定义，之后 `codex exec "ok"` 打印 `hook: SessionStart` 即生效；Claude Code 的用户级钩子不需批准。Codex 桌面端（ChatGPT.app）自带内核，与 CLI 共用 `~/.codex`：记忆、`hooks.json` 与 `[hooks.state]` 信任记录都是同一份，在 CLI 里信任过的钩子桌面端直接生效。不想装全局钩子的，在仓内 `.claude/settings.local.json` 与 `.codex/hooks.json` 写同样的 `SessionStart` 条目即可（Codex 侧需项目被信任）。
- **不做**：不反向写 Codex 存储；不动全局 `[features] memories` 开关；不解析 Codex 的 `MEMORY.md` 任务组与 `memory_summary.md`（再汇总、跨项目混写）；不进 llm-wiki（工具产物是原料，要进 wiki 走 ingest 编译）。

## worktree 里效果不变

`git worktree add` 只检出入库文件。接线写下的本机文件（团队仓里不入库的 `CLAUDE.md` / `AGENTS.md`、`.codex/config.toml`、项目级 skills、未入库的 `.memory`）在新 worktree 里全部缺失，会话就在裸仓里跑。setup 第 7 步往仓库共用的 hooks 目录装 `post-checkout` 钩子，任何方式建的 worktree（`git worktree add`、Claude Code 的 `--worktree` / `EnterWorktree`、superpowers，仓内或仓外）都触发，由 `worktree-share.sh`（Windows：钩子按 `$OSTYPE` 分派到 `worktree-share.ps1`）把根工作区的本机资产共享进去。

- **共享什么**：内置清单 `CLAUDE.md`、`AGENTS.md`、`GEMINI.md`、`.mcp.json`、`opencode.json`、`.env`、`.env.*`、`.memory`，以及六个工具配置目录 `.claude`、`.codex`、`.agents`、`.gemini`、`.opencode`、`.cursor`。工具目录按整目录列入：整目录被忽略就整目录软链（commands、hooks、skills、agents、settings 一并可见，不必逐项枚举）；目录含入库文件（如 `.claude/skills` 入库）或目录本身未被忽略（只有其下某些项被忽略）时，展开为其下被忽略的条目逐条共享。通配项在根工作区展开后逐项处理。只共享「根工作区有、未入库、已被忽略」的项；已入库的检出自带，未忽略的视为待提交只告警。
- **怎么共享**：文件复制，目录软链（`.memory` 必须只有一份，skills 只读）。Windows 目录只用符号链接（需开发者模式或管理员权限），建不出来时六个工具配置目录退回到只复制其下的文件、子目录不共享，其余目录整项不共享，均告警；不退回目录联接，见下表。
- **展开时跳过** `.claude/settings.local.json` 与 `.claude/worktrees`：前者 Claude Code v2.1.211 起在 worktree 里直接读主工作区那份，`autoMemoryDirectory` 与已授权限自动跟过来，复制出去反而会分叉；后者是 Claude 自建 worktree 的容器。`.claude` 整目录软链时两者随目录可见，是同一份文件，不分叉。Codex 没有这种回读，所以 `.codex/config.toml` 必须共享；Codex 的项目信任按主仓库判定，worktree 不用另登记。
- **自定义**：仓根放 `.worktree-share`，一行一项，`#` 注释，`!` 前缀剔除内置项（如 `!.env`），可带通配。目录本身含入库文件（如 `repos/.gitkeep` 入库、其下克隆被忽略）时展开为其下被忽略的条目逐条共享。
- **尾斜杠规则**：`.gitignore` 里 `.memory/` 这类带尾斜杠的规则只匹配真实目录、不匹配软链。脚本共享后复核，未被忽略就往仓库共用的 `.git/info/exclude` 补一行不带尾斜杠的路径，不碰团队 `.gitignore`。
- **手动**：接线前建的 worktree，或钩子没装的仓库：`bash ~/.agents/skills/agent-memory-setup/worktree-share.sh link <worktree路径>`；Windows `pwsh -File "$env:USERPROFILE\.agents\skills\agent-memory-setup\worktree-share.ps1" link <worktree路径>`。钩子里写的也是这个全局发现根路径（两种安装方式都有，不随开发 clone 或临时 worktree 移动）。对根工作区执行只提示不动作。

## 常见错误

- 只做了 Claude 一侧，以为「别的工具本来就读 AGENTS.md 所以没问题」：它们读到的规则文件里根本没有记忆规则。
- 装了全局规则又每仓 `--with-rule`：两份同义规则并存，不出错但多余。
- 自己发明一个 `MEMORY.md` 约定但没设 `autoMemoryDirectory`：Claude 的自动记忆仍写在仓库外。
- 把 `autoMemoryDirectory` 写进入库的 `settings.json`：被忽略，且带上了本机绝对路径。
- 在未被信任的临时目录里测 Codex 项目配置，得出「项目级配置无效」的错误结论。
- 以为 `.codex/config.toml` 里关三项能挡住 Codex 记忆：它的后台管线只读全局配置；旧接线写的关闭块现由 setup 迁移删除，Codex 记忆改为同步回 `.memory/`。

## 与 llm-wiki 的关系

[llm-wiki](https://github.com/vvnocode/llm-wiki)（个人知识工作台）的 `bootstrap.sh` / `bootstrap.ps1` 直接调用本 skill 的 setup 脚本完成接线（未装先装 [vvnocode/AGENTS.md](https://github.com/vvnocode/AGENTS.md)），自己只保留 Skill 全局挂载等工作台特有步骤；它原有的 worktree 共享脚本与钩子由本 skill 的机制替代，工作台特有的共享项（`repos`、采集游标、私有区）写进其仓根 `.worktree-share`。两者分工：本 skill 管**接线**（一份指令、一份仓内记忆、各工具指过来、worktree 等效），llm-wiki 管**知识**（跨项目的机制、决策、案例）。内容层面 `.memory/` 记做事方式（偏好、纠正、约束、指针），wiki 记事实结论（对象、机制、决策、案例），判据与机械规则见 llm-wiki 的 `docs/schemas/分区与共享.md`「与 `.memory/` 的分工」。
