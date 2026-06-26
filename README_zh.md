<div align="right">
  <a href="README.md">English</a> | <strong>中文</strong>
</div>

# gitsage

> **基于 git 上下文的 AI 开发效率助手。**
> 读取本地 git 状态，记住你的习惯，把它们转化为清晰的表达——commit message、站会内容、PR 描述、代码溯源。

[![PyPI](https://img.shields.io/pypi/v/gitsage-ai.svg)](https://pypi.org/project/gitsage-ai/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-200%2B%20passing-brightgreen.svg)](#)

---

## 为什么需要 gitsage？

你已经知道改了什么，难的是把它简洁地表达出来。

每天都在做三件重复又需要"思考"的事：

- **写 commit message**：知道改了什么，但不知道怎么说
- **写站会**：做了很多，写出来要么太细要么太空
- **理解旧代码**：看懂了语法，但不知道「为什么这么写」

gitsage 读取你本地的 git 状态（staged diff、blame 历史、最近 commit），用 AI 把这些上下文转化为清晰的输出，并随着使用记住你的风格。

```
# 以前：盯着 diff 想半天写什么
$ git add src/payment/retry.py

# 现在：gitsage 替你想
$ gitsage commit

[1] ✅ feat(payment): 新增支付失败指数退避重试机制 [PAY-234]
       最多重试 3 次，间隔 1s/2s/4s。解决高并发下重复扣款问题。

[2]    feat: add payment retry logic with backoff strategy
[3]    fix(payment): handle transient payment gateway failures

回车接受 [1]，输入数字选择，e 编辑，q 退出：
```

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **Commit message 生成** | 输出 2-3 个候选，按置信度排序，自动从分支名提取 ticket 号 |
| **日报 / 站会生成** | 读取当日 commit，理解你实际做了什么，按受众格式化（技术团队 or 管理层） |
| **PR 描述生成** | 从分支 diff 生成完整 PR 正文——背景、变更说明、测试说明 |
| **代码溯源（explain）** | 迭代式 Agent，追溯代码的来源，回答「这段代码为什么存在」 |
| **风格学习** | 观察你的历史 commit，持续更新 `~/.gitsage/memory/`，输出越用越准 |
| **项目规范（CTX.md）** | 在仓库根目录放一个 `CTX.md`，commit 格式、受众、禁止词——整个团队共享 |
| **质量门控** | 输出在你看到之前已通过长度、格式、语言检验。CTX.md 里的规则由代码强制执行，不依赖 LLM 自觉 |
| **Git Hook 模式** | `gitsage install-hooks` 之后，`git commit` 会自动预填 AI 生成的 message |
| **多 LLM 支持** | DeepSeek、OpenAI、Anthropic，或本地 Ollama。数据不经过任何中间服务器 |

---

## 快速开始

### 安装

```bash
pip install gitsage-ai
```

### 配置

最简单的方式是交互式向导，一步步引导完成配置：

```bash
gitsage setup
```

也可以手动配置。gitsage 支持**任何 OpenAI-compatible 接口**（DeepSeek、OpenAI、月之暗面、硅基流动、Azure OpenAI 等），以及 Anthropic 和本地 Ollama：

```bash
# 本地模型 — 完全免费，数据不出本机
ollama pull qwen2.5:14b
gitsage model set ollama/qwen2.5:14b

# DeepSeek — 推荐的云端方案，约 ¥0.007/次
export DEEPSEEK_API_KEY=sk-...
gitsage model set deepseek-v4-flash

# OpenAI
export OPENAI_API_KEY=sk-...
gitsage model set gpt-4o-mini

# 任何 OpenAI-compatible 接口（自定义 base_url）
# 编辑 ~/.gitsage/config.yml：
#
# llm:
#   provider: openai-compatible
#   base_url: https://api.your-provider.com   # 硅基流动、月之暗面、Azure 等
#   api_key: ${YOUR_API_KEY}
#   model: your-model-name
```

### 使用

```bash
git add .
gitsage commit      # 生成 commit message，选一个，完成
gitsage standup     # 今天做了什么？
gitsage explain src/auth/token.py  # 这段代码为什么存在？
```

---

## 工作原理

gitsage 分三层运行：

```
┌──────────────────────────────────────────────────────────┐
│  Harness 层  （确定性规则、质量门控）                       │
│  → 无论 LLM 输出什么，CTX.md 规则都会被强制执行            │
├──────────────────────────────────────────────────────────┤
│  Context 层  （git 状态 + 项目配置 + 记忆）                │
│  → staged diff、blame、历史 commit、CTX.md、学到的风格     │
├──────────────────────────────────────────────────────────┤
│  LLM 层      （单次调用 or Agent 循环）                    │
│  → commit/standup：一次结构化调用                          │
│  → explain/catchup：带工具调用的 Agent 循环                │
└──────────────────────────────────────────────────────────┘
```

**上下文在本地组装。** 你的代码从终端直接发往你配置的 LLM，不经过 gitsage 的任何服务器。

---

## 命令列表

### 核心命令

```bash
gitsage commit                    # 生成 commit message（交互式）
gitsage commit --mode print       # 只打印候选，不提交
gitsage commit --mode execute     # 静默提交第一个候选
gitsage commit --estimate         # 显示 token 预估后退出

gitsage standup                   # 今日工作摘要
gitsage standup --print           # 纯文本输出（适合管道）

gitsage pr                        # 当前分支的 PR 标题 + 描述
gitsage pr --base-branch develop  # 与指定分支对比

gitsage explain <file>            # 这段代码为什么存在？
gitsage explain <file> --local    # 跳过 GitHub API，仅用本地 git 历史

gitsage catchup                   # 查看最近一段时间的变更摘要
```

### 配置管理

```bash
gitsage setup                     # 交互式 LLM 配置向导
gitsage preferences               # 设置语言、emoji、commit 风格…
gitsage preferences --show        # 查看当前偏好
gitsage config init               # 分析 git 历史 → AI 草拟 CTX.md → 交互式修改
gitsage config show               # 查看当前配置
```

### 模型管理

```bash
gitsage model list                # 当前模型 + 推荐列表
gitsage model set deepseek-v4-flash
gitsage model test                # 验证连接是否正常
```

### 工具命令

```bash
gitsage doctor                    # 检查环境和配置
gitsage install-hooks             # 安装 prepare-commit-msg git hook
gitsage memory show               # 查看当前仓库的学习记忆
gitsage memory clear              # 清空当前仓库的记忆
gitsage skill list                # 列出所有可用 skill
gitsage skill show <name>         # 查看 skill 完整内容
gitsage skill add [name]          # 交互式创建新 skill
gitsage skill edit <name>         # 用 $EDITOR 编辑 skill
```

---

## CTX.md — 项目规范

在仓库根目录放一个 `CTX.md` 并提交到 git，整个团队共享同一套 AI 约定：

```markdown
# CTX.md — 项目上下文

## 项目背景
移动端支付服务，Java + Spring Boot。
核心模块：order-service、payment-service、user-service。

## Commit 规范
格式：feat(<模块>): <中文描述>
示例：feat(payment): 新增支付失败重试机制

## 站会格式
面向技术 lead，简洁，聚焦影响。

## 规则
always:
  - 从分支名提取 JIRA ticket 号 [PAY-XXX]
never:
  - commit message 中包含文件路径
  - 站会里提及实现细节
```

没有 CTX.md 也能用，只是输出会更通用一些。

`gitsage config init` 可以自动分析你的 git 历史，生成初版 CTX.md，降低冷启动成本。

---

## 记忆系统

gitsage 观察你的提交历史，为每个仓库维护一个记忆文件：

```markdown
# ~/.gitsage/memory/Moyonx_gitsage_a1b2c3.md

## 用户习惯（自动更新）
- Commit 风格：祈使句，中文，不用 emoji
- 常用 scope：cli, agent, harness
- 分支规律：feat/PAY-XXX-描述 → 自动追加 [PAY-XXX]

## 当前工作上下文
- 正在做：gitsage explain（代码溯源功能）
- 最近重大变更：偏好系统
```

每累积 20 条原始观测，触发一次 LLM 汇总提炼，生成结构化偏好摘要。持续使用一周后，输出质量会明显提升。

---

## Git Hook 集成

```bash
gitsage install-hooks
```

之后，`git commit` 会自动预填 AI 生成的 message：

```
# 编辑器打开时已预填：
feat(payment): 新增指数退避重试机制 [PAY-234]

# 审阅、按需修改、保存 → commit 完成
# git commit -m "..." 依然正常工作（跳过 hook）
```

---

## Skills 扩展

Skills 是给 gitsage 注入领域专属推理规则的 Markdown 文件，存放在 `.gitsage/skills/<名称>/SKILL.md`。

```bash
gitsage skill list               # 查看已安装的 skill（名称、触发方式、来源）
gitsage skill show <name>        # 查看 skill 完整内容（语法高亮）
gitsage skill add [name]         # 交互式向导创建 skill
gitsage skill edit <name>        # 用 $EDITOR 编辑
```

示例：创建一个 `jira-standup` skill，让站会内容自动带上 JIRA ticket 引用。skill 的 description 始终在上下文中；完整内容按需加载。

---

## MCP Server — Claude Code / Cursor 集成

gitsage 可作为 MCP Server，向 Claude Code、Cursor 等 AI 编辑器暴露本地 git 状态和生成能力。注册后，AI 编辑器可以直接查询仓库状态，或触发完整的 gitsage 生成流程。

### 配置

```bash
# 1. 安装 gitsage
pip install gitsage-ai

# 2. 注册到 Claude Code
claude mcp add gitsage -- gitsage mcp serve

# 3. 重启 session，工具即可用
```

Cursor 用户，在 `.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "gitsage": {
      "command": "gitsage",
      "args": ["mcp", "serve"]
    }
  }
}
```

或使用内置安装命令：

```bash
gitsage mcp install                      # Claude Desktop
gitsage mcp install --client cursor      # Cursor
gitsage mcp status                       # 查看任意客户端的配置片段
```

### 可用工具

| 工具 | 返回内容 |
|------|---------|
| `get_git_status` | 分支名、staged 文件、工作区状态 |
| `get_staged_diff` | 当前 staged 变更的完整 diff |
| `get_recent_commits` | 最近 N 条 commit（sha、作者、日期、message） |
| `get_branch_info` | 当前分支 + 最后一条 commit |
| `get_file_history` | 指定文件的 git log |
| `generate_commit_message` | AI 生成 commit 候选（读取 CTX.md + 记忆 + 偏好） |
| `generate_standup` | AI 生成今日站会内容（读取 CTX.md + 偏好） |

### 在 Claude Code 中使用

注册后，在新 session 里自然语言提问即可：

```
「我的 staged 变更里有什么？」
「帮我生成 commit message」
「今天做了什么？生成站会内容」
「gitsage/cli.py 最近有什么变动？」
```

`generate_commit_message` 和 `generate_standup` 会走完整 gitsage pipeline——CTX.md 规则、记忆、质量门控、偏好注入——全部在你的 AI 编辑器里触发。

所有数据在**本地处理**，diff 和 commit 历史不会离开你的机器。

---

## 支持的 LLM

| Provider | 配置方式 | 说明 |
|----------|---------|------|
| **Ollama** | `ollama pull qwen2.5:14b` | 本地免费，数据不出本机 |
| **DeepSeek** | `export DEEPSEEK_API_KEY=sk-...` | 推荐云端方案，约 ¥0.007/次 |
| **OpenAI** | `export OPENAI_API_KEY=sk-...` | 兼容所有 OpenAI-compatible 接口 |
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-...` | 质量最好，成本较高 |
| **自定义** | 在配置文件中设置 `base_url` | 任何 OpenAI-compatible 端点 |

```bash
# 随时切换
gitsage model set deepseek-v4-flash
gitsage model set ollama/qwen2.5:14b
gitsage model test
```

---

## 配置文件

`~/.gitsage/config.yml`（全局配置）：

```yaml
llm:
  provider: openai-compatible
  model: deepseek-v4-flash
  api_key: ${DEEPSEEK_API_KEY}       # 支持环境变量展开
  base_url: https://api.deepseek.com

commit:
  default_mode: interactive           # interactive | print | execute

preferences:
  language: auto                      # zh | en | auto
  commit_emoji: false
  commit_scope: true
  commit_length: standard             # brief | standard | detailed
  ticket_format: auto                 # auto | jira | github | none
  standup_audience: technical         # technical | nontechnical
```

---

## 隐私说明

- **你的代码不经过 gitsage 的任何服务器。** 数据从你的终端直接发送到你配置的 LLM provider。
- **Ollama** = 完全离线，什么都不出本机。
- **云端 provider** = diff 和 commit 历史发送给你配置的 API（DeepSeek、OpenAI 等），受其隐私政策约束。
- gitsage 默认无遥测。

---

## 开发者指引

```bash
git clone https://github.com/Moyonx/gitsage
cd gitsage
pip install -e ".[dev]"

# 运行测试
pytest

# 用本地代码运行
python -m gitsage commit
```

### 项目结构

```
gitsage/
├── config.py          # 配置加载（ENV > ~/.gitsage/config.yml > CTX.md）
├── cli.py             # Typer CLI — 所有命令
├── wizard.py          # 交互式配置向导
├── preferences.py     # 用户偏好问卷和持久化
├── context/
│   ├── git_reader.py  # GitPython 封装 — staged diff、blame、历史
│   ├── ctx_reader.py  # CTX.md 解析器 — 项目规范
│   ├── memory.py      # 两阶段学习系统
│   └── builder.py     # 组装 LLM 调用所需的上下文
├── agent/
│   ├── llm.py         # LLM 抽象层 — Anthropic SDK + OpenAI-compatible
│   ├── models.py      # Pydantic 输出模型
│   └── prompts.py     # system prompt 和 user prompt builder
├── harness/
│   ├── quality_gate.py    # 输出校验和重试
│   ├── override.py        # 确定性规则执行
│   └── hooks.py           # 生命周期 hook 运行器
├── skills/
│   └── loader.py      # SKILL.md 发现和加载
└── renderer/
    └── interactive.py # 基于 Rich 的交互式 commit 选择 UI
```

---

## 参与贡献

欢迎提 Pull Request。对于较大的变更，请先开 Issue 讨论方案。

```bash
# 提交前请确保测试通过
pytest tests/
```

特别欢迎贡献新的 Skill 文件（针对常见工作流的 SKILL.md）。

---

## License

[MIT](LICENSE)
