# AGENTS.md：跨工具 AI 编程协作规范

一份可移植、可审查、可版本控制的 AI 编程协作规范。以单一 Markdown 文件为规则源，通过符号链接或项目级入口复用于 Claude Code、Codex、Gemini CLI、OpenCode、Cursor、DeepSeek Harness 等工具。

[快速开始](#快速开始) · [支持矩阵](#支持矩阵) · [接线一个仓库](#接线一个仓库) · [两件套](#两件套) · [项目级接入](#项目级接入) · [更新](#更新规则) · [参与贡献](#参与贡献) · [许可](#许可)

## 项目定位

不同 AI 编程工具使用不同的规则文件名和加载位置，但规则内容往往高度重合。本项目将通用协作规范集中维护在 [`AGENTS.md`](./AGENTS.md) 中，再按各工具约定的文件名进行挂载，从而解决以下问题：

- **单一规则源**：只维护一份正文，避免多个工具配置逐渐分叉。
- **跨工具复用**：同一套工程纪律可以映射到不同工具的用户级或项目级入口。
- **可审查更新**：规则改动通过 Git diff、提交和 Pull Request 留下记录。
- **隐私可控**：仓库版本不包含个人路径、所在地、凭据或内部地址。
- **按项目覆盖**：通用规则作为默认值，具体项目仍可提供更精确的本地约束。

正文文件名取跨工具约定的 `AGENTS.md`（Codex、OpenCode、Cursor、DeepSeek Harness 都读它），而不是某一家的 `CLAUDE.md`；Claude Code 通过软链到 `~/.claude/CLAUDE.md` 读同一份。仓库 2026-09-08 由 `vvnocode/claude.md` 改名而来。

这不是提示词合集，也不绑定某个模型。它关注的是长期稳定的工程行为：先理解再修改、控制变更范围、用证据验证结果、明确分支与交付流程。

## 规则结构

[`AGENTS.md`](./AGENTS.md) 分为三个层次：

| 部分 | 内容 | 维护方式 |
|---|---|---|
| 个人偏好与自定规则 | 语言、表达、注释和版本控制偏好 | 可按个人或团队需要调整 |
| 通用行为准则 | 降低常见 AI 编码错误的基本原则 | 尽量保持通用、简洁 |
| 工程纪律 | 任务分级、测试、调试、验证、评审和收尾流程 | 根据实践结果持续修订 |

规则刻意不写工具专有命令。工具名称、加载位置和安装方式统一维护在本 README 中。

第四部分「全局知识工作台（llm-wiki）」是可选路由：仅当本机存在 `~/.llm-wiki`（一个指向个人知识工作台实例的软链，由该工作台的 bootstrap 创建）时生效，未安装者整部分自动失效，规则文件无需任何本机路径。

## 支持矩阵

下表列出已核对官方规则机制的工具。工具版本会持续变化，实际加载顺序应以对应官方文档为准。

| 工具 | 用户级入口 | 项目级入口 | 全局 Skill 发现根 | 官方说明 |
|---|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `./CLAUDE.md` | `~/.claude/skills/` | [Memory](https://code.claude.com/docs/en/memory) |
| Codex | `~/.codex/AGENTS.md` | `./AGENTS.md` | `~/.codex/skills/` | [Codex manual](https://developers.openai.com/codex/codex-manual.md) |
| Gemini CLI | `~/.gemini/GEMINI.md` | `./GEMINI.md` | 待核验 | [Provide context with GEMINI.md](https://geminicli.com/docs/cli/gemini-md/) |
| OpenCode | `~/.config/opencode/AGENTS.md` | `./AGENTS.md` | `~/.config/opencode/skills/`，也扫 `~/.claude/skills/` 与 `~/.agents/skills/` | [Rules](https://opencode.ai/docs/en/rules/) |
| DeepSeek Harness | `$DSH_HOME/AGENTS.md`，默认 `~/.dsh/AGENTS.md` | `./AGENTS.md` 或 `./CLAUDE.md` | `~/.agents/skills/` | [Agent instructions](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/README.md) |
| Cursor | 设置中的 User Rules | `./AGENTS.md` 或 `.cursor/rules/` | 待核验 | [Rules](https://cursor.com/docs/rules) |

“支持”表示目标工具能够读取对应入口中的 Markdown 规则，不表示不同工具会以完全相同的优先级、上下文预算或合并算法处理它。项目规则、目录级规则和组织托管规则可能覆盖本文件。

「全局 Skill 发现根」列供 Skill 挂载时参考（本仓 `install.sh` 就按它把 `skills/agent-memory-setup` 挂到三处）：`~/.agents/skills/` 是跨工具约定俗成的 canonical 根，Cline、Dexto、Kimi、Warp、Zed 等只读它；Claude Code 与 Codex 不扫它、只认自己的目录。把一个 skill 软链到 `~/.agents/skills/`、`~/.claude/skills/`、`~/.codex/skills/` 三处即可覆盖上表已核验的工具。标「待核验」的格子尚未按实物核对，不要凭印象填写。本表是这三类路径的唯一正本，其他仓库只链接、不另维护。

## 快速开始

一条命令把仓库 clone 到 `~/.vvnocode/rules`，把 `AGENTS.md` 软链到各工具的用户级规则入口（Claude Code、Codex、Gemini CLI、OpenCode、DeepSeek Harness），并把 `skills/agent-memory-setup` 软链到三处全局 Skill 发现根。幂等：重跑即更新，已存在的目标只告警不覆盖。

**macOS / Linux**：

```bash
curl -fsSL https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/install.sh | bash
```

**Windows**（系统自带的 Windows PowerShell 5.1 即可）：

```powershell
irm https://raw.githubusercontent.com/vvnocode/AGENTS.md/main/install.ps1 | iex
```

Windows 建文件软链需要开发者模式或管理员权限；没有时脚本改为复制文件并在末尾打上标记，之后每次重跑安装会刷新这些副本。旧 Windows 上 `irm` 报「基础连接已经关闭」时，先执行 `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072` 打开 TLS 1.2。

脚本行为：

- 托管 clone 在 `~/.vvnocode/rules`（Windows `%USERPROFILE%\.vvnocode\rules`）；环境变量 `RULES_REPO_DIR` 改位置，`RULES_REPO_URL` 改为 fork。按早期 README 装在 `~/.config/vibe-coding-rules` 的，重跑安装会自动搬过来并重指链接。
- 入口已是你自己的规则文件，或指向别处的链接：只告警不动。先把自己的规则并入，再手动换成链接。
- 在本仓 clone 内运行 `./install.sh`（Windows `powershell -ExecutionPolicy Bypass -File .\install.ps1`）：软链直接指向该 clone，不联网、不建托管副本，开发用。
- 卸载：删掉各入口的软链，再删 `~/.vvnocode/rules`。
- 脚本纯 ASCII、提示为英文：Windows PowerShell 5.1 的 `irm` 不去 BOM，`-File` 又按本地代码页解码，两条路径同时成立只有纯 ASCII 一种写法。

Cursor 的全局 User Rules 通过设置界面维护，不是稳定的文件挂载入口。需要全局使用时，可将规则正文加入 Cursor User Rules；需要跟随项目版本控制时，使用下方的项目级接入方式。

## 接线一个仓库

全局规则装好后，让某个仓库里的 Claude Code、Codex、dsh、OpenCode 共用一份指令（`AGENTS.md`，`CLAUDE.md` 只含一行 `@AGENTS.md`）与一份仓内记忆（`.memory/`），在仓库目录下执行：

```bash
~/.vvnocode/rules/skills/agent-memory-setup/setup.sh [仓库路径]
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.vvnocode\rules\skills\agent-memory-setup\setup.ps1" [仓库路径]
```

脚本同时装一个 `post-checkout` 钩子：之后不管用 `git worktree add`、Claude Code 的 `--worktree` 还是别的工具建 worktree，根工作区被 gitignore 的本机资产（规则文件、`.memory`、项目级 skills 与 agents、`.codex/config.toml`、`.mcp.json`、`.env`）都会自动共享进去，worktree 里的会话与根工作区效果一致。文件复制、目录软链（Windows 无特权时退回目录联接）；仓根放 `.worktree-share` 可增删共享项。接线前建的 worktree 手动跑一次 `worktree-share.sh link <worktree路径>`。参数、验证方式与各工具的坑见 [skills/agent-memory-setup](./skills/agent-memory-setup/SKILL.md)。

## 两件套

本仓是 vvnocode 两件套之一。两者各管一层、互相独立、安装顺序随意，缺任何一个另一个照常工作：

| 仓库 | 管什么 | 装到哪 | 缺了会怎样 |
|---|---|---|---|
| [AGENTS.md](https://github.com/vvnocode/AGENTS.md)（本仓） | 跨工具全局规则（含「项目记忆」读写规则与 llm-wiki 路由段），以及给任意仓库接线的 skill `agent-memory-setup`（一份指令、一份仓内记忆、worktree 共享钩子） | `~/.vvnocode/rules`：规则软链到各工具的用户级规则入口，skill 软链到三处全局 Skill 发现根 | 规则没人下发、仓库不接线：偏好走各工具自带记忆，worktree 里丢本机资产；llm-wiki 的 bootstrap 会自动补装 |
| [llm-wiki](https://github.com/vvnocode/llm-wiki) | 个人知识工作台：跨项目的机制、决策、案例 | 目录自选，`~/.llm-wiki` 软链指过去。它是数据仓、可一机多实例，不进 `~/.vvnocode` | 规则里的「全局知识工作台」整段失效，不查不写 |

运行时只有两处条件门把两者接起来：仓内有 `.memory/` 才读写记忆，本机有 `~/.llm-wiki` 才查写 wiki。原第三件 [vvnocode/skills](https://github.com/vvnocode/skills) 只有 `agent-memory-setup` 一个 skill，2026-09-08 并入本仓后归档；重跑本仓安装命令会把指向旧位置的 skill 链接重指过来。llm-wiki 按其 README 或 `SETUP-FOR-AI.md` 部署。

## 项目级接入

用户级规则适合作为个人默认值。项目级入口有两种用法：个人本地接入可以使用符号链接但不应提交；团队共享规则应将实际文件内容加入项目并纳入版本控制，不能提交指向个人配置目录的绝对符号链接。

个人本地接入可根据目标工具选择它识别的文件名：

```bash
# 先设置本仓库中规则源的绝对路径。
RULES_FILE="$HOME/.vvnocode/rules/AGENTS.md"
PROJECT_ROOT="/path/to/project"

# 只创建本机实际使用的入口，不覆盖已有项目规则，也不要提交这些绝对路径链接。
ln -s "$RULES_FILE" "$PROJECT_ROOT/CLAUDE.md"  # Claude Code
ln -s "$RULES_FILE" "$PROJECT_ROOT/AGENTS.md"  # Codex、OpenCode、Cursor、DeepSeek Harness
ln -s "$RULES_FILE" "$PROJECT_ROOT/GEMINI.md"  # Gemini CLI
```

团队共享时，应把适用的通用规则复制或整理到项目自己的规则文件中，再提交该实际文件。这样每个协作者检出仓库后都能获得相同配置，也可以在项目内独立审查后续变更。

项目级接入前需要注意：

1. **先检查现有文件**：项目自己的 `CLAUDE.md`、`AGENTS.md` 或 `GEMINI.md` 通常包含不可替代的构建和测试命令，不应直接覆盖。
2. **选择适当作用域**：个人偏好不一定适合提交给团队；团队仓库应保留可共同执行的规则。
3. **理解优先级**：嵌套目录、组织策略和工具设置可能提供更高优先级的指令。
4. **避免重复加载**：同一工具只保留一个明确入口，除非其官方机制要求分层规则。

如果项目已有规则文件，更稳妥的方式是摘取本仓库中的通用章节，或在工具支持导入语法时显式引用，而不是替换整个文件。

记忆与指令是两回事：规则文件只约束「仓内 `.memory/` 存在时怎么读写」，不负责搭建。让 Claude Code、Codex、dsh、OpenCode 在同一仓库共用一份 `AGENTS.md` 与一份仓内记忆的接法（引用行、`autoMemoryDirectory`、关闭 Codex 自带记忆、信任门禁、worktree 共享钩子），见本仓 [skills/agent-memory-setup](./skills/agent-memory-setup/SKILL.md)，一键脚本见上文「接线一个仓库」。

## 更新规则

重跑安装命令即可：托管副本快进更新，所有挂载入口随后读取新内容。想先审查再更新：

```bash
RULES_HOME="$HOME/.vvnocode/rules"
git -C "$RULES_HOME" fetch origin
git -C "$RULES_HOME" diff HEAD..origin/main -- AGENTS.md README.md
git -C "$RULES_HOME" merge --ff-only origin/main
```

全局规则会影响多个项目。不要在未审查 diff 的情况下自动定时更新。

## 自定义与分叉

推荐通过 Fork 维护个人或团队版本：

1. 在第一部分调整语言、注释、时区和协作偏好。
2. 保持通用原则不依赖某个模型或工具命令。
3. 将项目特定的构建、测试和部署指令留在项目仓库。
4. 删除不适用于自身工作流的规则，避免指令之间互相冲突。
5. 提交前检查用户名、家目录、内部域名、令牌和凭据是否已经移除。

仓库的 [`.gitignore`](./.gitignore) 已排除常见本地配置、环境变量、私钥、凭据文件和临时 worktree，但忽略规则不能代替提交前审查。

## 仓库结构

```text
.
├── .gitignore   # 本地配置、凭据和临时文件的忽略规则
├── .memory/     # 本仓自己的跨会话记忆（按 AGENTS.md「项目记忆」节读写）
├── AGENTS.md    # 跨工具复用的唯一规则源
├── docs/        # specs/ 与 plans/：影响后续开发的设计结论
├── install.sh   # 一键安装（macOS / Linux）：clone 到 ~/.vvnocode/rules，软链各规则入口与 skill
├── install.ps1  # 一键安装（Windows），纯 ASCII
├── LICENSE      # CC0 1.0 Universal 完整法律文本
├── README.md    # 安装、兼容性、维护和贡献说明
├── skills/
│   └── agent-memory-setup/   # 单仓接线 skill：setup.sh/.ps1、worktree-share.sh/.ps1、post-checkout 钩子模板、Codex 探针
└── tests/       # 安装、接线与 worktree 共享脚本的离线契约测试：python3 -m unittest discover -s tests
```

`.ps1` 测试需要 `pwsh`（或 Windows PowerShell），没有则自动跳过；三个 Windows 专属用例（目录联接兜底、联接计已就位、删 worktree 不伤根工作区）只在 Windows 上运行。

无需额外维护 changelog 文档。历史变更由 Git 提交记录保存；长期有效的安装方式和兼容性结论维护在本 README 中。

## 设计原则

- **规则正文与工具适配分离**：正文描述行为，README 描述如何加载。
- **默认值与项目约束分离**：全局规则提供基线，项目规则负责具体命令和架构事实。
- **可验证性优先**：所有“完成”“修复”“通过”都应有本轮执行证据。
- **最小必要修改**：每一处变更都应能够追溯到明确需求。
- **安全公开**：公开版本不包含个人身份信息、机器路径或秘密材料。

## 参与贡献

欢迎通过 Issue 或 Pull Request 改进规则。提交前请确认：

- 变更适用于多个项目或工具，而不是单个仓库的偶然需求。
- 新规则解决了明确问题，并且没有与现有条目重复或冲突。
- 工具路径、文件名和加载行为附有官方文档依据。
- 文档示例不会覆盖用户已有配置，也不包含真实凭据或个人路径。
- Pull Request 说明包含修改原因、影响范围和验证方式。

涉及工具兼容性的变更，请同时更新支持矩阵和安装示例。

## 来源与致谢

- 通用行为准则：逐句中译自 [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) 的 `CLAUDE.md`。
- 工程纪律：提炼自 [obra/superpowers](https://github.com/obra/superpowers) v6.3.0。本文件始终加载，只保留始终有效的纪律，不照搬插件按需加载时的完整仪式。

这些来源提供方法论基础，本仓库负责跨工具适配、中文维护和公开版本的隐私处理。

## 许可

除另有说明及明确标注来源的第三方材料外，本仓库中项目贡献者拥有权利的原创内容采用 [CC0 1.0 Universal](./LICENSE)：任何人均可复制、修改、组合和再发布，也可用于商业用途，不要求署名。

本 README 中明确注明上游来源的翻译、改编内容，以及链接指向的第三方材料，不会因为本项目采用 CC0 而被重新授权；这些内容仍受其各自权利状态和适用条款约束。CC0 只能放弃或许可贡献者实际拥有的权利。

新增 `LICENSE` 不需要重写 Git 历史。它表示项目维护者从包含该文件的版本开始，对其有权处分的现有及后续原创贡献适用 CC0。
