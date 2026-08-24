# CLAUDE.md：跨工具 AI 编程协作规范

一份可移植、可审查、可版本控制的 AI 编程协作规范。以单一 Markdown 文件为规则源，通过符号链接或项目级入口复用于 Claude Code、Codex、Gemini CLI、OpenCode、Cursor、DeepSeek Harness 等工具。

[快速开始](#快速开始) · [支持矩阵](#支持矩阵) · [项目级接入](#项目级接入) · [更新](#更新规则) · [参与贡献](#参与贡献) · [许可](#许可)

## 项目定位

不同 AI 编程工具使用不同的规则文件名和加载位置，但规则内容往往高度重合。本项目将通用协作规范集中维护在 [`CLAUDE.md`](./CLAUDE.md) 中，再按各工具约定的文件名进行挂载，从而解决以下问题：

- **单一规则源**：只维护一份正文，避免多个工具配置逐渐分叉。
- **跨工具复用**：同一套工程纪律可以映射到不同工具的用户级或项目级入口。
- **可审查更新**：规则改动通过 Git diff、提交和 Pull Request 留下记录。
- **隐私可控**：仓库版本不包含个人路径、所在地、凭据或内部地址。
- **按项目覆盖**：通用规则作为默认值，具体项目仍可提供更精确的本地约束。

这不是提示词合集，也不绑定某个模型。它关注的是长期稳定的工程行为：先理解再修改、控制变更范围、用证据验证结果、明确分支与交付流程。

## 规则结构

[`CLAUDE.md`](./CLAUDE.md) 分为三个层次：

| 部分 | 内容 | 维护方式 |
|---|---|---|
| 个人偏好与自定规则 | 语言、表达、注释和版本控制偏好 | 可按个人或团队需要调整 |
| 通用行为准则 | 降低常见 AI 编码错误的基本原则 | 尽量保持通用、简洁 |
| 工程纪律 | 任务分级、测试、调试、验证、评审和收尾流程 | 根据实践结果持续修订 |

规则刻意不写工具专有命令。工具名称、加载位置和安装方式统一维护在本 README 中。

## 支持矩阵

下表列出已核对官方规则机制的工具。工具版本会持续变化，实际加载顺序应以对应官方文档为准。

| 工具 | 用户级入口 | 项目级入口 | 官方说明 |
|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `./CLAUDE.md` | [Memory](https://code.claude.com/docs/en/memory) |
| Codex | `~/.codex/AGENTS.md` | `./AGENTS.md` | [Codex manual](https://developers.openai.com/codex/codex-manual.md) |
| Gemini CLI | `~/.gemini/GEMINI.md` | `./GEMINI.md` | [Provide context with GEMINI.md](https://geminicli.com/docs/cli/gemini-md/) |
| OpenCode | `~/.config/opencode/AGENTS.md` | `./AGENTS.md` | [Rules](https://opencode.ai/docs/en/rules/) |
| DeepSeek Harness | `$DSH_HOME/AGENTS.md`，默认 `~/.dsh/AGENTS.md` | `./AGENTS.md` 或 `./CLAUDE.md` | [Agent instructions](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/README.md) |
| Cursor | 设置中的 User Rules | `./AGENTS.md` 或 `.cursor/rules/` | [Rules](https://cursor.com/docs/rules) |

“支持”表示目标工具能够读取对应入口中的 Markdown 规则，不表示不同工具会以完全相同的优先级、上下文预算或合并算法处理它。项目规则、目录级规则和组织托管规则可能覆盖本文件。

## 快速开始

### macOS / Linux

以下方式把仓库安装到用户配置目录，并为支持文件型全局规则的工具创建符号链接。命令不会覆盖已有目标文件；如果目标已经存在，请先阅读并手动合并原有规则。

```bash
# 将规则仓库安装到稳定路径，后续更新不会改变符号链接目标。
RULES_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-coding-rules"
git clone https://github.com/vvnocode/claude.md.git "$RULES_HOME"
RULES_FILE="$RULES_HOME/CLAUDE.md"

# 创建各工具需要的用户级配置目录。
DSH_HOME_RESOLVED="${DSH_HOME:-$HOME/.dsh}"
mkdir -p \
  "$HOME/.claude" \
  "$HOME/.codex" \
  "$HOME/.gemini" \
  "${XDG_CONFIG_HOME:-$HOME/.config}/opencode" \
  "$DSH_HOME_RESOLVED"

# 同一规则源按各工具约定的文件名挂载。
ln -s "$RULES_FILE" "$HOME/.claude/CLAUDE.md"
ln -s "$RULES_FILE" "$HOME/.codex/AGENTS.md"
ln -s "$RULES_FILE" "$HOME/.gemini/GEMINI.md"
ln -s "$RULES_FILE" "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/AGENTS.md"
ln -s "$RULES_FILE" "$DSH_HOME_RESOLVED/AGENTS.md"
```

Cursor 的全局 User Rules 通过设置界面维护，不是稳定的文件挂载入口。需要全局使用时，可将规则正文加入 Cursor User Rules；需要跟随项目版本控制时，使用下方的项目级接入方式。

### Windows PowerShell

Windows 创建符号链接通常需要启用开发者模式或使用具备相应权限的终端。以下命令同样不会覆盖已有目标文件。

```powershell
# 将仓库克隆到当前用户的稳定配置目录。
$RulesHome = Join-Path $HOME ".config\vibe-coding-rules"
git clone https://github.com/vvnocode/claude.md.git $RulesHome
$RulesFile = Join-Path $RulesHome "CLAUDE.md"

# DeepSeek Harness 可通过 DSH_HOME 改写全局配置目录，未设置时使用 ~/.dsh。
$DshHome = if ([string]::IsNullOrWhiteSpace($env:DSH_HOME)) {
    Join-Path $HOME ".dsh"
} else {
    $env:DSH_HOME
}

# 定义支持文件型全局规则的工具入口。
$Targets = @(
    (Join-Path $HOME ".claude\CLAUDE.md"),
    (Join-Path $HOME ".codex\AGENTS.md"),
    (Join-Path $HOME ".gemini\GEMINI.md"),
    (Join-Path $HOME ".config\opencode\AGENTS.md"),
    (Join-Path $DshHome "AGENTS.md")
)

# 逐项创建父目录和符号链接；目标已存在时命令会报错并保留原文件。
foreach ($Target in $Targets) {
    $TargetDirectory = Split-Path $Target -Parent
    New-Item -ItemType Directory -Force -Path $TargetDirectory | Out-Null
    New-Item -ItemType SymbolicLink -Path $Target -Target $RulesFile | Out-Null
}
```

如果环境不允许创建符号链接，可以复制文件到目标位置，但复制方式不会自动获得后续更新。

## 项目级接入

用户级规则适合作为个人默认值。项目级入口有两种用法：个人本地接入可以使用符号链接但不应提交；团队共享规则应将实际文件内容加入项目并纳入版本控制，不能提交指向个人配置目录的绝对符号链接。

个人本地接入可根据目标工具选择它识别的文件名：

```bash
# 先设置本仓库中规则源的绝对路径。
RULES_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-coding-rules/CLAUDE.md"
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

## 更新规则

符号链接安装只需更新仓库，所有挂载入口会立即读取新内容：

```bash
# 仅接受快进更新，避免在安装目录中意外产生合并提交。
RULES_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-coding-rules"
git -C "$RULES_HOME" pull --ff-only
```

更新全局规则前建议先查看变更：

```bash
# 获取远端后审查当前版本与远端默认分支之间的差异。
RULES_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/vibe-coding-rules"
git -C "$RULES_HOME" fetch origin
git -C "$RULES_HOME" diff HEAD..origin/main -- CLAUDE.md README.md
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
├── CLAUDE.md    # 跨工具复用的唯一规则源
├── LICENSE      # CC0 1.0 Universal 完整法律文本
└── README.md    # 安装、兼容性、维护和贡献说明
```

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

本项目的通用行为准则翻译自 Andrej Karpathy 风格的工程提示词整理，上游来源见 [`CLAUDE.md`](./CLAUDE.md) 中的链接；工程纪律参考 [obra/superpowers](https://github.com/obra/superpowers) 的方法，并针对不依赖插件的使用方式进行了整理。

这些来源提供方法论基础，本仓库负责跨工具适配、中文维护和公开版本的隐私处理。

## 许可

除另有说明及明确标注来源的第三方材料外，本仓库中项目贡献者拥有权利的原创内容采用 [CC0 1.0 Universal](./LICENSE)：任何人均可复制、修改、组合和再发布，也可用于商业用途，不要求署名。

`CLAUDE.md` 中明确注明上游来源的翻译、改编内容，以及链接指向的第三方材料，不会因为本项目采用 CC0 而被重新授权；这些内容仍受其各自权利状态和适用条款约束。CC0 只能放弃或许可贡献者实际拥有的权利。

新增 `LICENSE` 不需要重写 Git 历史。它表示项目维护者从包含该文件的版本开始，对其有权处分的现有及后续原创贡献适用 CC0。
