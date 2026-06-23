# gitsage — 产品设计文档

> **gitsage** — Git-native AI developer workflow assistant.
> 理解你在做什么、帮你表达出来、记住你的习惯。

---

## 一、项目定位

### 核心问题

开发者每天面临三个重复性的「表达困难」：

| 场景 | 问题 |
|------|------|
| 写 commit message | 知道改了什么，不知道怎么简洁地说出来 |
| 写站会发言 | 做了很多事，写出来要么太细要么太空 |
| 理解旧代码 | 看懂了语法，不知道「为什么这么写」 |

本质相同：**你有上下文（git 历史、代码、PR、Issue），但没有工具帮你转化成可读的表达。**

### 解决方案

gitsage 是一个 **git-native AI 开发者工作流助手**：

- 把你的 git 状态组装成 LLM 可理解的结构化上下文
- 用 Skills 做不同任务的专业推理
- 用 Harness 层做质量保证和确定性控制
- 跨会话记住你的习惯，越用越准

### 和现有工具的关系

```
Claude Code  →  通用编程 Agent，重，做整个 feature
gitsage      →  专属 git 工作流，轻，理解并表达你的工作

不竞争，可组合：
gitsage 作为 MCP Server 后，Claude Code 可以调用 gitsage
获取 git 状态，两者形成上下游关系
```

### 差异化核心

| 维度 | 其他工具 | gitsage |
|------|---------|---------|
| commit 生成 | 每次从零开始 | 记住你的风格，越用越准 |
| 上下文 | 只看 diff | CTX.md + 记忆 + git 历史三层叠加 |
| 质量保证 | LLM 自由发挥 | Harness 层质量门控 + 确定性规则 |
| 集成方式 | 独立工具 | CLI + MCP Server，可被任何 MCP 客户端调用 |
| LLM | 绑定特定平台 | 任意 provider，支持本地 Ollama |

---

## 二、命令设计（已确认）

### 核心命令

```bash
gitsage commit              # 生成 commit message（交互式选择，自动提交）
gitsage standup             # 生成今日站会内容
gitsage explain <file>      # 解释代码为什么这么写（Agent 模式）
gitsage pr                  # 生成当前分支的 PR 描述
gitsage catchup             # 查看最近变更摘要（交互选择时间范围）
```

### commit 多模式设计（已确认）

不同工作习惯的用户有不同的使用方式，全部支持：

```bash
# 模式1：交互式（默认）
# 展示 2-3 个候选，用户选择后自动执行 git commit
gitsage commit

# 模式2：只打印，用户自己决定
gitsage commit --print
# 输出：feat(payment): 新增支付重试机制 [PAY-234]

# 模式3：静默执行，直接用第一个候选提交
gitsage commit --execute

# 模式4：Git Hook 模式，供 prepare-commit-msg 调用
gitsage commit --hook

# 一键安装 Git Hook（装完后只用 git commit 即可）
gitsage install-hooks
```

**交互式模式的 UX 示例：**

```
$ gitsage commit

分析变更中... ✓

[1] ✅ feat(payment): 新增支付重试机制，指数退避策略 [PAY-234]
       置信度: 高 | 检测到 JIRA ticket | 符合项目风格
[2]    feat: add payment retry with exponential backoff
       置信度: 中 | 英文备选
[3]    fix: handle payment timeout with retry logic
       置信度: 中 | 偏向修复语义

Enter 接受[1]，输入数字选择，e 编辑，q 退出：
↵
✅ [main abc1234] feat(payment): 新增支付重试机制，指数退避策略 [PAY-234]
```

**默认模式可在配置中设置：**

```yaml
# ~/.gitsage/config.yml
commit:
  default_mode: interactive  # interactive | print | execute
```

### catchup 时间选择（已确认）

```bash
# 无参数时交互选择
$ gitsage catchup

查看最近多久的变更？
  [1] 今天
  [2] 本周（7 天） ← 推荐
  [3] 两周
  [4] 自定义

选择 [1-4] 或直接输入天数：2

正在分析最近 7 天的 23 个 commits...

# 也支持直接指定
gitsage catchup --days 7
gitsage catchup --days 14
gitsage catchup --since v1.2.0      # 从某个 tag 开始
gitsage catchup --since 2024-03-01  # 从某个日期开始
```

### 管理命令

```bash
# 模型管理
gitsage model list
gitsage model set deepseek/deepseek-v4-flash
gitsage model test

# Skill 管理
gitsage skill list
gitsage skill add <name>
gitsage skill show <name>
gitsage skill edit <name>

# MCP 管理
gitsage mcp install          # 注册进 Claude Desktop / Cursor
gitsage mcp status
gitsage mcp start / stop

# 记忆管理
gitsage memory show [--repo]
gitsage memory clear [--repo]

# 配置管理
gitsage config init          # 分析 git 历史，智能预填 CTX.md
gitsage config show
gitsage config set <key> <value>

# 工具集成
gitsage install-hooks        # 安装 prepare-commit-msg git hook
gitsage install-completion   # 安装 shell tab 补全（bash/zsh/fish）
gitsage doctor               # 检查环境、配置、API 连通性

# 其他
gitsage --version
gitsage upgrade
gitsage --estimate           # 在任何命令前加此 flag，预估 token 用量
```

### --estimate flag（已确认）

```bash
$ gitsage explain src/payment/retry.py --estimate

预计消耗：
  模型: deepseek-v4-flash
  预计调用次数: 3-6 次（Agent 模式，取决于关联 PR 数量）
  预计 token: 8,000 - 15,000
  预计费用: ¥0.02 - ¥0.04

继续执行？[Y/n]:
```

---

## 三、系统架构

### 三层工程架构

```
┌────────────────────────────────────────────────────────────────┐
│  Harness Layer（确定性控制层）                                   │
│                                                                │
│  Lifecycle Hooks → Quality Gate → Deterministic Override       │
│                                                                │
│  「LLM 在框架内工作，规则层保证确定性」                            │
├────────────────────────────────────────────────────────────────┤
│  Context Layer（上下文组装层）                                   │
│                                                                │
│  CTX.md + MEMORY.md + Git State + Skill                       │
│                                                                │
│  「给 LLM 恰当的信息，不是原始数据堆砌」                           │
├────────────────────────────────────────────────────────────────┤
│  Execution Layer（执行层）                                      │
│                                                                │
│  单次 LLM 调用（commit/standup/pr）                             │
│  Agent 循环（explain/catchup）                                 │
│                                                                │
│  「根据任务复杂度选择执行模式」                                    │
└────────────────────────────────────────────────────────────────┘
```

### 完整执行流程

```
用户输入（gitsage commit）
         │
         ▼
[首次运行检查]
  未同意隐私提示 → 展示提示，记录同意
  未配置 API    → 友好引导配置
         │
         ▼
[Git State Reader]
  staged diff / recent commits / branch name / repo info
         │
         ▼
[Context Builder]
  CTX.md（项目规范）
  + MEMORY.md（用户习惯）
  + Git State（当前状态）
  + Skill（推理框架）
         │
         ▼
[Pre-Hook]
  执行 .gitsage/hooks/pre-commit.sh（确定性脚本）
  失败 → 中止并提示原因
         │
         ▼
[LLM Execution]
  简单任务 → 单次调用 + Prompt Caching
  复杂任务 → Agent 循环（最多 10 步）
         │
         ▼
[Quality Gate]
  检查：长度 / 格式 / 语言 / 必要字段
  不通过 → 携带反馈重试（最多 3 次）
         │
         ▼
[Deterministic Override]
  强制注入 ticket 号 / 过滤禁止词 / 语言校正
         │
         ▼
[Post-Hook]
  执行 .gitsage/hooks/post-commit.sh
  异步更新 MEMORY.md
         │
         ▼
[Output]
  交互式：展示候选，用户选择，执行 git commit
  --print：输出到 stdout
  --execute：静默执行
```

---

## 四、上下文系统（Context Layer）

### 文件体系

```
全局（跨项目）
~/.gitsage/
  ├── config.yml             # LLM、全局偏好、commit 默认模式
  ├── memory/
  │   └── {repo-hash}.md     # 按仓库存储的自动记忆
  └── skills/                # 全局 Skills（跨项目复用）

项目级（提交 git，团队共享）
项目根目录/
  ├── CTX.md                 # 项目规范（commit 格式、standup 要求等）
  ├── CTX.local.md           # 个人覆盖（加入 .gitignore）
  └── .gitsage/
      ├── hooks/             # 生命周期脚本
      │   ├── pre-commit.sh
      │   ├── post-commit.sh
      │   └── pre-standup.sh
      └── skills/            # 项目专属 Skills
```

### CTX.md 示例

```markdown
# CTX.md — 项目上下文配置

## 项目背景
外卖订单系统，Java + Spring Boot。
核心模块：order-service, payment-service, user-service。
涉及 payment 模块的变更需要特别注意并发安全。

## Commit 规范
格式：<emoji> <类型>(<模块>): <描述>
类型：feat/fix/refactor/test/docs
语言：中文
示例：✨ feat(order): 新增订单重试机制

## Standup 格式
汇报对象：技术 Leader，正式简洁，重点说影响。
包含：今日完成 + 明日计划 + 阻塞项（没有可省略）

## 规则
always:
  - commit message 必须包含 JIRA ticket 号（从 branch name 提取）
  - 涉及 payment 模块标注 ⚠️

never:
  - standup 里不提具体文件名
  - commit message 超过 72 字符（中文 36 字）
```

### gitsage config init 智能初始化（已确认）

不生成通用模板，而是分析项目的 git 历史：

```bash
$ gitsage config init

正在分析 git 历史（最近 50 条 commits）...

检测到：
  ✅ Commit 风格：emoji + 中文，类型前缀（feat/fix）
  ✅ 主要模块：payment-service (68%), order-service (21%)
  ✅ 平均长度：28 字符
  ✅ JIRA 格式：[PAY-XXX]
  ✅ 提交频率：工作日 10-18 点

已生成 CTX.md，请确认或修改：
→ 用编辑器打开 CTX.md...
```

### MEMORY.md 自动更新机制（已确认：两阶段）

**阶段一：即时追加**（每次命令结束后异步执行）

```markdown
## 原始观测记录（自动追加）
2024-03-15 commit: "✨ feat(payment): 新增重试机制 [PAY-234]"
  → 风格: emoji+中文, 模块: payment, 有ticket
2024-03-15 commit: "🐛 fix(order): 修复超时问题 [ORD-89]"
  → 风格: emoji+中文, 模块: order, 有ticket
...
```

**阶段二：LLM 汇总提炼**（每 20 次调用触发一次）

```markdown
## 用户习惯（LLM 提炼，最后更新：2024-03-15）
- 始终使用 emoji + 中文
- 总是包含 JIRA ticket
- 倾向 payment 和 order 模块
- 平均描述长度 28 字

## 项目记忆
- 当前进行中：活动优惠系统改造 (#PROJ-892)
- 上次重大重构：退款模块（2024-03 完成）
```

---

## 五、Skills 系统

### Skill 文件格式

```markdown
# .gitsage/skills/commit/SKILL.md

---
name: commit
description: 生成符合项目规范的 git commit message
trigger: auto
---

## 推理步骤
1. 分析 staged diff 的核心变更意图（找目的，不列文件）
2. 对照 CTX.md 里的规范
3. 从 branch name 提取 JIRA ticket 号
4. 生成主推方案 + 2 个备选
5. 为每个候选标注置信度和理由

## 输出格式
{
  "candidates": [
    {
      "message": "string",
      "confidence": "high|medium|low",
      "reason": "置信度理由"
    }
  ],
  "warning": "可选：变更太复杂建议拆分 commit"
}

## 注意
- 不要罗列文件名，要提炼意图
- 变更跨多个不相关模块时，建议用户拆分
```

---

## 六、Harness 层

### Lifecycle Hooks

```bash
# .gitsage/hooks/pre-commit.sh
#!/bin/bash
# 防止提交包含密钥（确定性规则，LLM 无法绕过）
if git diff --staged | grep -E "(password|secret|api_key)\s*="; then
    echo "❌ 检测到可能的密钥，请检查后重新 stage"
    exit 1
fi
```

| Hook | 触发时机 |
|------|---------|
| pre-commit | gitsage commit 执行前 |
| post-commit | commit message 生成后（更新 MEMORY.md） |
| pre-standup | gitsage standup 执行前 |
| post-standup | 内容生成后 |
| pre-explain | gitsage explain 执行前 |
| session-start | 任何 gitsage 命令启动时 |

### Quality Gate

```python
COMMIT_RULES = [
    Rule("max_length", chars=72, on_fail="truncate_and_retry"),
    Rule("language_match", source=ctx.commit_lang, on_fail="retry"),
    Rule("has_verb_start", on_fail="retry"),
    Rule("no_file_paths", on_fail="filter"),
]
# 不通过 → 携带违规信息重试，最多 3 次
# 3 次后仍不通过 → 返回最佳候选 + 警告标注
```

### Deterministic Override

```python
class DeterministicOverride:
    def apply(self, output, ctx_config):
        # 强制注入 JIRA ticket（规则层保证，不依赖 LLM）
        if ctx_config.rules.always.inject_ticket:
            ticket = extract_from_branch(git.branch())
            if ticket and ticket not in output:
                output = f"{output} [{ticket}]"

        # 强制过滤禁止内容
        for forbidden in ctx_config.rules.never.forbidden:
            output = output.replace(forbidden, "")

        return output
```

---

## 七、降级策略（已确认）

### API 不可用时

```bash
$ gitsage commit
⚠️  无法连接到 DeepSeek API

已为你整理变更摘要，供手动撰写参考：

变更文件：
  src/payment/RetryService.java  (+85 / -12)
  src/payment/PaymentClient.java (+23 / -5)

项目 commit 格式（来自 CTX.md）：
  ✨ feat(payment): <描述> [JIRA-号]

本地模式（数据不出网）：
  gitsage model set ollama/qwen2.5
```

### gitsage explain 无 GitHub Token 时

```bash
$ gitsage explain src/payment/RetryService.java
⚠️  未配置 GitHub Token，使用本地分析模式

正在分析本地 git 历史...

[本地分析结果 · 置信度: 中]

RetryService 在 3 个月前由 alice 引入（commit abc1234）
commit 信息显示：「feat(payment): 支付失败重试机制」

推测原因：支付超时后需要重试，但无法获取原始 Issue/PR 上下文。

配置 GitHub Token 可获取更完整的背景信息：
  export GITHUB_TOKEN=ghp_...
```

---

## 八、首次运行体验（已确认）

### 隐私提示（首次运行，仅此一次）

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📤 gitsage 将发送以下内容到 DeepSeek API：
   • staged diff（约 1,200 tokens ≈ ¥0.001）
   • CTX.md 项目配置
   • 最近 5 条 commit 记录

   数据直接发给 DeepSeek，不经过任何中间服务器。
   本地模式（零数据出网）：gitsage model set ollama/qwen2.5

继续？[Y/n]:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

选择后记录到 `~/.gitsage/config.yml`，之后不再询问。

### 零配置冷启动

```bash
# 没有 CTX.md 也能用
$ gitsage commit

⚡ 未检测到 CTX.md，使用通用模式。
   运行 gitsage config init 可生成项目专属配置，输出更准确。

[1] ✅ feat: add payment retry logic with exponential backoff
[2]    fix: handle payment timeout gracefully

Enter 接受[1]：
```

---

## 九、MCP Server 模式

### 配置

```json
// Claude Desktop 配置
{
  "mcpServers": {
    "gitsage": {
      "command": "gitsage",
      "args": ["mcp", "serve"]
    }
  }
}
```

### 暴露的工具

| 工具 | 功能 |
|------|------|
| `get_staged_diff` | 获取当前 staged 变更 |
| `get_recent_commits` | 获取最近 N 条 commit |
| `get_git_status` | 获取仓库当前状态 |
| `get_branch_info` | 获取分支和关联 PR |
| `get_file_history` | 获取文件 git 历史 |
| `generate_commit_message` | 调用完整 gitsage commit 流程 |
| `generate_standup` | 调用完整 gitsage standup 流程 |

---

## 十、安装与配置（已确认）

### 安装方式

```bash
# pip（主要，Python 开发者首选）
pip install gitsage

# brew（macOS 用户可选）
brew install gitsage

# npx（无需安装直接运行）
npx gitsage commit
```

### 初始化

```bash
gitsage config init          # 分析 git 历史，智能生成 CTX.md
gitsage doctor               # 检查环境配置
gitsage install-completion   # 安装 shell tab 补全
gitsage install-hooks        # 安装 git hooks（可选）
```

### 环境变量

```bash
DEEPSEEK_API_KEY=sk-...     # DeepSeek（推荐，性价比高）
ANTHROPIC_API_KEY=sk-...    # Anthropic Claude（可选）
OPENAI_API_KEY=sk-...       # OpenAI（可选）
GITHUB_TOKEN=ghp_...        # gitsage explain/catchup 需要（可选，无则降级）
```

---

## 十一、技术选型

| 层次 | 技术 | 选型理由 |
|------|------|---------|
| 语言 | Python 3.11+ | AI 生态完整，开发效率高 |
| CLI | Typer + Rich | 类型安全，美观输出 |
| LLM | anthropic + openai SDK | 覆盖 Anthropic 和 OpenAI-compatible（DeepSeek 等） |
| 数据验证 | Pydantic v2 | Structured Output，类型安全 |
| MCP | mcp Python SDK | 官方 MCP SDK |
| 本地存储 | SQLite + Markdown | 轻量，无需额外服务 |
| 测试 | pytest + pytest-mock | 单元测试 + mock |
| 打包 | hatchling + pyproject.toml | 现代 Python 打包标准 |

---

## 十二、开发路线图

### Phase 1（Week 1-4）：核心价值
- [ ] `gitsage commit`（多模式 + 质量门控 + 交互式选择）
- [ ] `gitsage standup`
- [ ] `gitsage pr`
- [ ] CTX.md 解析 + MEMORY.md 两阶段更新
- [ ] 多 LLM provider 支持（DeepSeek/Anthropic/OpenAI/Ollama）
- [ ] 首次运行隐私提示
- [ ] 零配置冷启动体验
- [ ] `gitsage config init`（git 历史分析 + 智能预填）
- [ ] `gitsage doctor` + `--estimate` flag
- [ ] Shell tab 补全（`gitsage install-completion`）
- [ ] API 不可用降级策略

### Phase 2（Week 5-8）：Harness 层 + 生态
- [ ] Lifecycle Hooks 系统（pre/post hooks）
- [ ] Quality Gate 引擎
- [ ] Deterministic Override 层
- [ ] Skills 系统（加载、管理、社区安装）
- [ ] `gitsage install-hooks`（git hook 模式）
- [ ] `gitsage model / skill / memory` 管理命令
- [ ] Windows 基础兼容（Phase 2，不是 Phase 4）

### Phase 3（Week 9-12）：Agent 功能
- [ ] `gitsage explain`（Agent 循环，本地降级模式）
- [ ] `gitsage catchup`（交互式时间选择，Agent 分析）
- [ ] 自适应重试策略（模型降级、provider 切换）
- [ ] MCP Server 完整实现

### Phase 4（Week 13+）：平台化
- [ ] 社区 Skill 仓库
- [ ] `gitsage upgrade` 自动更新
- [ ] 插件市场基础
- [ ] Agent Teams 模式（explain + verify 双 Agent）

---

## 十三、非功能性设计

### 隐私
- API Key 只存本地
- git 内容发送到用户配置的 LLM，不经任何中间服务
- 首次运行明确告知
- 支持 Ollama 本地模式，数据完全不出网

### 性能目标

| 命令 | 目标响应时间 |
|------|------------|
| gitsage commit | < 3s |
| gitsage standup | < 5s |
| gitsage pr | < 8s |
| gitsage explain | < 20s（Agent 模式） |
| gitsage catchup | < 30s |

### 兼容性
- macOS / Linux：Phase 1 完整支持
- Windows：Phase 2 基础兼容
- Python 3.11+

---

*文档版本：v0.2（已确认所有核心设计决策）*
*最后更新：2026-06-23*
