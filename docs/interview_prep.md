# gitsage 项目面试准备手册

> 本文档用于面试前的系统复盘，涵盖项目介绍、架构理解、以及所有可能被追问的技术/行为类问题与最佳回答。

---

## 一、项目一句话介绍

**gitsage** 是一个基于 git 上下文的 AI 开发效率助手。它读取本地 git 状态（diff、commit 历史、blame），通过结构化 prompt + 确定性 Harness 层生成 commit message、站会内容、PR 描述、代码溯源报告等，并作为 MCP Server 向 Claude Code / Cursor 等 AI 编辑器开放能力。

**技术栈**：Python · typer · Rich · Pydantic · LLM（多 provider）· MCP

**亮点**：不是简单调 API，有 Quality Gate + Deterministic Override 做确定性质量控制；`explain` 是真正的迭代式 Agent；记忆系统跨会话学习用户习惯；发布至 PyPI，200+ 单元测试。

---

## 二、架构速览

```
┌─────────────────────────────────────────────┐
│              CLI / MCP Server               │  ← 用户入口
├─────────────────────────────────────────────┤
│             Harness Layer                   │
│   QualityGate  │  DeterministicOverride     │  ← 确定性规则层
│   HookRunner   │  ContextBuilder            │
├─────────────────────────────────────────────┤
│              Agent Layer                    │
│   LLM Client（multi-provider）              │  ← AI 推理层
│   Prompt Builder  │  Output Models          │
├─────────────────────────────────────────────┤
│             Context Layer                   │
│   CTX.md  │  Memory  │  Skills  │  GitReader│  ← 上下文组装层
└─────────────────────────────────────────────┘
```

**三层的分工：**
- **Context Layer**：从 git、文件系统、用户配置中读取所有上下文，组装成结构化对象
- **Agent Layer**：把上下文转化为 prompt，调用 LLM，把输出解析为 Pydantic 模型
- **Harness Layer**：在 LLM 之上叠加确定性校验和规则强制执行，保证输出符合工程规范

---

## 三、核心模块速查

| 模块 | 文件 | 职责 |
|------|------|------|
| GitReader | `context/git_reader.py` | 读取 staged diff、commit 历史、blame、branch diff |
| CTXReader | `context/ctx_reader.py` | 解析 CTX.md，提取 commit 规则、always/never 约束、语言 |
| MemoryManager | `context/memory.py` | 两阶段记忆：追加观测 + LLM 汇总 |
| SkillLoader | `skills/loader.py` | 加载 SKILL.md，project 优先于 global |
| ContextBuilder | `context/builder.py` | 组装以上四者为 CommitContext / StandupContext 等 |
| LLMClient | `agent/llm.py` | 统一 provider 抽象，支持 OpenAI / Anthropic / DeepSeek / Ollama |
| Prompts | `agent/prompts.py` | 所有 system + user prompt builder |
| QualityGate | `harness/quality_gate.py` | 长度、语言、动词开头校验 |
| DeterministicOverride | `harness/override.py` | 强制注入 ticket 号、过滤禁止词 |
| HookRunner | `harness/hooks.py` | pre/post-commit 等生命周期钩子 |
| MCP Server | `mcp/server.py` | 暴露 7 个工具供 AI 编辑器调用 |
| UserPreferences | `preferences.py` | 语言/emoji/scope/ticket 偏好持久化 |

---

## 四、面试问题集

---

### 📌 A. 项目背景与动机

---

**Q1：为什么做这个项目？解决了什么问题？**

**A：**
开发者每天都在做三件机械但又需要"思考"的事：写 commit message（知道改了什么，但不知道怎么简洁地表达）、写站会（做了很多事，说出来要么太细要么太空）、理解老代码（看懂了语法，但不知道"为什么这么写"）。这三件事本质相同：你有上下文（git 历史、diff、PR），但缺少工具把它转化成可读的表达。

gitsage 就是做这个转化的工具，而且不是简单地"把 diff 扔给 ChatGPT"——它能读本地 git 状态、记住你的习惯、遵守项目规范、并以 MCP Server 的方式被 AI 编辑器调用。

> **追问：这和直接用 ChatGPT / Claude 有什么区别？**
>
> 直接用 ChatGPT 要手动粘贴 diff，输出格式不可控，不了解你的项目规范，每次从零开始，也无法集成进 git 工作流。gitsage 的差异在于：**上下文自动组装**（不需要手动粘贴）、**确定性质量控制**（Harness 层保证输出规范）、**跨会话记忆**（记住你的偏好）、**MCP 集成**（AI 编辑器可以直接调用）。本质上是把 LLM 嵌进 git 工作流，而不是让你手动在两个工具之间搬运信息。

---

**Q2：市面上有没有类似工具？你的差异化在哪里？**

**A：**
有几类相关工具：
- **GitHub Copilot commit**：只做 commit message，依托 VS Code，不支持其他 provider，无法感知项目规范
- **conventional-commits CLI**：只做格式约束，不用 AI
- **aicommits / commitgpt**：做 commit message，但没有记忆、没有质量控制、不做其他工作流场景

gitsage 的差异点：
1. **全工作流覆盖**：commit / 站会 / PR / 代码溯源 / 历史摘要
2. **Harness 层**：LLM 上面加了确定性质量控制，这是别的工具没有的
3. **跨会话记忆**：越用越懂你，其他工具每次从零开始
4. **MCP Server**：可以被 Claude Code、Cursor 等 AI 编辑器直接调用，是"被集成"的工具而不是独立工具
5. **多 provider**：不绑定某个 LLM

> **追问：Harness 层具体解决了什么问题？**
>
> LLM 的输出是概率性的，同一个 diff 不同次调用可能给出不同风格的 commit message——有时带 emoji 有时不带，有时中文有时英文，有时有 scope 有时没有。如果项目规范要求"必须有 scope、必须用中文、必须带 JIRA ticket"，纯 LLM 方案无法 100% 保证。Harness 层的 DeterministicOverride 做的是：无论 LLM 给什么，都在输出上强制注入 ticket 号（从 branch name 提取），强制过滤禁止词。Quality Gate 则校验长度、语言、动词开头，不通过则重试，最多 3 次。

---

**Q3：为什么做成 CLI 而不是 VS Code 插件或 Web 应用？**

**A：**
几个考量：
1. **git 工作流天然是终端场景**，开发者在 terminal 里 `git add`、`git commit`，CLI 工具可以无缝接入，不需要切换上下文
2. **可以被 git hook 调用**：`gitsage install-hooks` 把它装进 `prepare-commit-msg`，之后只需 `git commit` 就自动触发
3. **MCP Server 模式**弥补了 IDE 集成缺失——通过 `gitsage mcp serve`，Claude Code / Cursor 可以直接调用，等于间接做了 IDE 集成，但不绑定任何一个 IDE
4. **Python CLI 开发速度快**，适合个人项目快速验证

---

**Q4：项目的目标用户是谁？**

**A：**
主要是**习惯命令行的开发者**，使用 git 的日常工作流，想用 AI 辅助但不想每次手动粘贴上下文的人。特别适合：
- 对 commit message 质量有要求的团队（可以共享 CTX.md 规范）
- 使用 Claude Code / Cursor 的 AI 辅助开发者（通过 MCP 集成）
- 需要写日报/站会但不想花太多时间整理 git 历史的人

---

### 📌 B. 系统设计与架构

---

**Q5：为什么要设计三层架构？直接调 LLM 不就够了？**

**A：**
直接调 LLM 有三个问题：
1. **上下文散乱**：每次命令都要手动组装 diff + 历史 + 规范，代码重复且难以维护
2. **输出不可控**：LLM 的概率性输出无法保证规范合规
3. **职责混乱**：提示词工程、业务逻辑、输出验证全混在一起，难以测试

三层架构解决这三个问题：
- **Context Layer** 统一做上下文组装，每个命令只需调用对应的 builder，输入数据标准化
- **Agent Layer** 专注 prompt 工程和 LLM 调用，输出用 Pydantic 模型约束
- **Harness Layer** 专注确定性规则执行，和 LLM 解耦，可以独立测试

而且这个分层让每一层都可以独立演进：比如换一个 LLM provider 只需改 Agent Layer，不影响 Harness 或 Context。

> **追问：Context Layer 是怎么决定给 LLM 多少上下文的？**
>
> 目前是按优先级和长度做截断：CTX.md 全量传入（通常比较短），Memory 全量传入，diff 截断到合理长度（避免超过模型上下文窗口），recent commits 取最近 10 条的 subject line。Skills 内容按 trigger 类型决定是否注入。这个策略相对简单，更精细的做法是做语义压缩或 RAG，但对当前场景已够用。

---

**Q6：CTX.md 的设计理念是什么？**

**A：**
CTX.md 是一个纯 Markdown 文件，放在项目根目录并提交到 git，让整个团队共享同一套 AI 约定。设计原则：
1. **人类可读**：不是配置文件（YAML/JSON），是自然语言，开发者可以直接阅读和修改
2. **可版本控制**：放在 git 里，变更有历史，code review 可见
3. **结构化但宽松**：有 `## Commit Rules`、`## Rules` 等标准 section，parser 按 section 提取，其余内容作为背景信息全量传给 LLM

`config init` 命令可以分析 git 历史自动生成初版 CTX.md，降低冷启动成本。

> **追问：CTX.md 的 always/never 规则是怎么被使用的？**
>
> CTXReader 解析 `## Rules` section，提取 `always:` 和 `never:` 下的条目（YAML 格式）。这些规则有两个用途：一是注入到 user prompt 中让 LLM 遵循，二是传给 DeterministicOverride 做硬性过滤。也就是说 `never` 规则会在 LLM 输出后被代码强制执行，不依赖 LLM 自觉。

---

**Q7：记忆系统为什么设计成两阶段？直接每次调 LLM 汇总不行吗？**

**A：**
每次都调 LLM 汇总有两个问题：
1. **延迟**：commit 之后的记忆更新会阻塞 CLI，用户体验差
2. **成本**：频繁 LLM 调用成本高，即使是便宜的模型也不合理

两阶段设计：
- **Phase 1（即时追加）**：守护线程（daemon thread）异步写入观测记录到本地 Markdown 文件，完全不阻塞主流程，成本接近零
- **Phase 2（定期汇总）**：每累积 20 条原始观测才触发一次 LLM 汇总，把 Summary 节替换为新的提炼内容，清空原始观测

这样在 20 次提交之内，记忆读取的是上一次 LLM 汇总的内容（紧凑，token 少）；第 20 次提交后触发一次汇总，后台执行，用户无感知。

> **追问：守护线程（daemon thread）是什么意思？为什么要用守护线程？**
>
> Python 的 daemon thread 会在主进程退出时自动结束，不会阻止进程退出。用守护线程的好处是：主 CLI 流程完成后可以直接退出，不需要等待记忆写入完成。记忆更新是 best-effort 的，偶尔丢失一条观测没关系，不能为了记忆更新让用户等待。

---

**Q8：Skills 系统的设计逻辑是什么？**

**A：**
Skills 是一个扩展点，让用户或团队在不改主体代码的情况下，给特定命令注入领域专属推理规则。

设计上是 `SKILL.md` 文件放在 `.gitsage/skills/<name>/` 目录下，有 YAML frontmatter（name、description、trigger）和 Markdown body（给 LLM 的指令内容）。

trigger 有两种：
- `auto`：对应命令每次都自动注入（比如 commit skill 每次生成 commit 时注入）
- `manual`：只有明确指定时才用

SkillLoader 会优先加载 project-level skills（`.gitsage/skills/`），全局 skills（`~/.gitsage/skills/`）作为 fallback，支持 team 共享规范（提交到 git）和个人全局规范（不提交）并存。

---

**Q9：偏好注入为什么要放在 system prompt 顶部，而不是底部或 user prompt？**

**A：**
这是实验得出的结论。LLM 对 system prompt 中较早出现的指令给予更高权重，这和注意力机制（attention）以及训练时的模板格式有关。

具体问题背景：CTX.md 里可能写"use English"（项目规范），但用户偏好设置了"中文"。如果把用户偏好放在 system prompt 底部或 user prompt，LLM 会倾向于遵从 CTX.md 的项目规范（因为它出现得更早或更显眼）。

解决方案：把语言偏好约束以"═══ 最高优先级 ═══"格式显式声明在 system prompt 最顶部，并写明"此设置覆盖 CTX.md 里的任何语言规则"。实测这样能可靠地让 LLM 遵从用户偏好而不是项目规范。

> **追问：这是怎么发现这个问题的？**
>
> 在测试时发现用户设置了中文偏好，但 CTX.md 里有英文提交规范，结果 LLM 有时输出英文。调试后发现是 prompt 顺序的问题——LLM 在同一 prompt 里看到两条矛盾指令时，倾向于遵从更早出现的那条。把用户偏好提到顶部并加强措辞后，问题解决。

---

### 📌 C. 核心功能实现

---

**Q10：explain 命令的 Agent 是怎么工作的？**

**A：**
`explain` 是项目里唯一真正的迭代式 Agent，流程如下：

1. **初始上下文**：读取目标文件内容 + git blame（每行对应的 commit hash）+ 最近 N 条涉及该文件的 commit log
2. **第一轮 LLM 调用**：给模型初始信息，让它判断：是否已有足够信息回答"这段代码为什么存在"，还是需要更多上下文
3. **工具调用**：如果模型认为信息不足，它会"调用工具"（在实现上是 LLM 输出一个结构化的"下一步动作"，代码根据动作执行）：
   - 获取某个 commit 的完整 diff
   - 通过 GitHub API 获取关联 PR 的 title/body
   - 通过 GitHub API 获取关联 Issue 的内容
4. **循环**：将新获取的信息追加到上下文，再次调用 LLM，直到模型判断信息充分
5. **最终输出**：结构化报告，包含解释、置信度、引用来源（commit SHA、PR 号、Issue 号）
6. **降级**：无 GitHub Token 时跳过 API 调用，纯本地 git 历史分析

> **追问：这是 ReAct 模式吗？**
>
> 思路类似 ReAct（Reason + Act），但实现上简化了：模型的每次输出包含两部分——对当前信息的分析，以及"需要什么额外信息"的结构化声明。代码读取"需要什么"，执行对应工具，再把结果塞回 context 重新调用。没有实现完整的 ReAct 框架，但达到了类似的效果：模型控制信息获取过程，而不是固定流程。

> **追问：循环次数有没有上限？会不会无限循环？**
>
> 有最大迭代次数限制（默认 5 轮），超过后直接输出当前最佳结果并标注置信度为 low。实际上 2-3 轮通常就够了，因为一个文件的相关 PR/Issue 数量有限。

---

**Q11：commit 命令的完整流程是什么？**

**A：**
```
1. 检查 consent（首次运行提示隐私声明）
2. 检查 LLM 配置（未配置则引导 setup）
3. 读取 staged diff（git diff --staged）
4. 如果 staged 为空，提示用户先 git add
5. 运行 pre-commit hook（.gitsage/hooks/pre-commit.sh）
6. 组装上下文：staged diff + recent commits + CTX.md + Memory + Skill
7. 加载用户偏好，构建 personalised system prompt（偏好在顶部）
8. 调用 LLM，要求输出 CommitOutput（Pydantic 模型：candidates 列表）
9. 对每个 candidate 运行 QualityGate 校验
10. 对每个 candidate 运行 DeterministicOverride（注入 ticket 等）
11. 按模式派发：interactive / print / execute / hook
12. 如果用户确认提交，执行 git commit
13. 运行 post-commit hook
14. 异步触发记忆更新（daemon thread）
```

> **追问：QualityGate 不通过怎么处理？**
>
> QualityGate 校验不通过时，当前实现是记录日志并继续（不通过的 candidate 会在 UI 上显示警告标注）。更严格的做法是自动重试（携带违规信息重新调用 LLM），这在 Quality Gate 的设计文档里有描述，但当前版本为了减少 API 调用次数，选择了展示警告而非自动重试。这是一个已知的 trade-off。

---

**Q12：MCP Server 是如何实现的？**

**A：**
基于 `mcp` 这个 Python 包（Anthropic 官方 SDK），用 `stdio` 传输协议（标准输入输出）。Claude Code / Cursor 这类客户端启动时会 spawn 一个子进程（`gitsage mcp serve`），通过 stdin/stdout 进行 JSON-RPC 通信。

实现上：
1. `create_server()` 注册工具列表（`@server.list_tools()`）和工具调用处理器（`@server.call_tool()`）
2. 5 个读取工具（git 状态类）是同步函数，直接调用 GitReader
3. 2 个生成工具（`generate_commit_message`、`generate_standup`）需要调用 LLM，用 `asyncio.to_thread` 把同步的 LLM 调用包装进异步环境，避免阻塞事件循环
4. `mcp install` 命令负责把配置写入 Claude Desktop 的 `claude_desktop_config.json` 或 Cursor 的 `.cursor/mcp.json`

> **追问：为什么用 stdio 而不是 HTTP？**
>
> MCP 协议本身支持多种传输：stdio、HTTP SSE。stdio 的优势是零配置——不需要启动 server 监听端口，客户端直接 spawn 子进程，进程生命周期跟随客户端，不存在端口占用问题。对于本地工具来说 stdio 是更简洁的选择。

---

**Q13：如何处理超长 diff？**

**A：**
目前做简单截断：diff 超过一定字符数（约 4000 chars）时取前半部分。更合理的做法是按文件分组，优先保留变更行数多的文件，但当前版本用截断已能覆盖大多数场景。

`--estimate` flag 可以在调用 LLM 前预估 token 数，让用户决定是否继续（对大 diff 特别有用）。

> **追问：截断会不会导致 commit message 不准确？**
>
> 有可能。当 diff 非常大（比如重构了 20 个文件），截断后 LLM 只能看到部分变更，生成的 message 可能只描述了其中几个文件。这种情况下 gitsage 会在输出中加一个 `warning` 字段，提示"变更较复杂，建议拆分 commit"。这也是 gitsage 设计上鼓励小而聚焦的 commit 的原因之一。

---

### 📌 D. AI / LLM 工程

---

**Q14：为什么用 Pydantic 做结构化输出？**

**A：**
LLM 的原始输出是字符串，解析它有两个选择：
1. 自己写正则/JSON parser，脆弱，LLM 稍微输出格式不对就崩
2. 用结构化输出（Structured Output / Function Calling）+ Pydantic 验证

Pydantic 的优势：
- **Schema 自动生成**：`model.model_json_schema()` 直接生成 JSON Schema，注入 prompt
- **自动验证**：LLM 输出的 JSON 直接用 `Model.model_validate()` 验证，类型错误自动报错
- **IDE 友好**：有类型提示，代码写起来不容易出错

对于不支持 native structured output 的 provider（比如本地 Ollama），gitsage 把 JSON Schema 注入 system prompt，要求 LLM 输出符合格式的 JSON，再用 Pydantic 验证。支持 native structured output 的 provider（OpenAI、Anthropic）则直接用 API 的 function calling 能力。

> **追问：如果 LLM 输出的 JSON 格式不对怎么办？**
>
> 有 retry 机制（基于 tenacity 库），最多重试 3 次，每次带上验证错误信息重新调用。如果 3 次后仍然失败，抛出 `LLMValidationError`，CLI 层展示友好错误信息并触发降级逻辑。

---

**Q15：如何支持多个 LLM provider？抽象层是怎么设计的？**

**A：**
`BaseLLMClient` 是抽象基类，定义了 `complete(system, user, output_model)` 接口。不同 provider 实现这个接口：

- `OpenAICompatibleClient`：用 OpenAI Python SDK，支持 OpenAI、DeepSeek（OpenAI-compatible API）、Ollama
- `AnthropicClient`：用 Anthropic SDK

`create_llm_client(config)` 工厂函数根据配置的 `provider` 字段返回对应实例。

上层代码（Agent Layer、MCP Server）只依赖 `BaseLLMClient`，不关心具体 provider。

> **追问：切换 provider 有没有 prompt 兼容性问题？**
>
> 有，不同模型对 prompt 的敏感度不同。比如 Ollama 的本地小模型可能无法稳定输出 JSON，需要在 prompt 里更明确地要求格式。目前的处理是 prompt 对所有 provider 通用（在 system prompt 里明确要求输出 JSON），对格式要求较高的 provider 会触发更多重试。理想情况是对每个 provider 微调 prompt，但这会增加维护成本。

---

**Q16：Rate Limit 是怎么处理的？**

**A：**
tenacity 的 retry 装饰器 + 自定义 `LLMRateLimitError`。

当 API 返回 429 时，捕获异常，抛出 `LLMRateLimitError`，CLI 层识别这个异常后：
1. 展示友好提示：告诉用户遇到了限速
2. 显示 diff 摘要（文件列表 + 行数）供手动撰写参考
3. 提示切换到更低成本的模型（如 Ollama 本地零成本）

这是一个**优雅降级**设计：即使 LLM 不可用，用户依然能拿到有用信息，而不是直接报错退出。

---

**Q17：Token 预估是怎么做的？**

**A：**
用简单的字符数估算：`token_count ≈ len(text) / 4`（英文约 4 字符/token，中文约 1.5 字符/token，取折中）。这是粗略估算，不是精确值，但足够让用户有一个数量级的感知。

`--estimate` flag 在任何命令前使用，会打印估算的 token 数和大致费用，然后退出不调用 LLM。

精确估算需要对应模型的 tokenizer（如 OpenAI 的 tiktoken），出于简化选择了粗估。

---

### 📌 E. 工程质量与测试

---

**Q18：如何测试 LLM 相关的代码？不会每次都真的调 API 吧？**

**A：**
对，测试里完全不调真实 LLM。用 `unittest.mock.patch` 把 `llm.complete()` mock 掉，返回预设的 Pydantic 模型对象。

测试层次：
1. **单元测试**：每个模块单独测试，LLM 调用全部 mock
   - `test_context.py`：测 CTXReader、MemoryManager、SkillLoader
   - `test_harness.py`：测 QualityGate、DeterministicOverride
   - `test_agent.py`：测 prompt builder、output model 解析
   - `test_mcp.py`：测 `_dispatch` 和新增的 generation 函数
2. **CLI 命令测试**：用 typer 的 `CliRunner`，mock LLM 和文件系统
3. **MCP 生成工具测试**：mock ContextBuilder + LLMClient，验证 candidates 结构、error 处理等

200+ 测试覆盖所有核心模块，commit 之前本地跑通是硬性要求。

> **追问：有没有集成测试？**
>
> 目前没有端到端集成测试（需要真实 API key 和 git 仓库），这是个已知空白。Integration 测试会在 CI 里消耗 API 费用，暂时选择了不做。如果要做，可以针对特定场景准备 fixture（预设的 diff + 预设的 LLM 响应），用 VCR（录制回放）库记录真实 API 交互。

---

**Q19：为什么选择 pytest 而不是 unittest？**

**A：**
主要原因：
1. `tmp_path` fixture 自动创建/清理临时目录，测试文件隔离方便
2. `monkeypatch` fixture 做环境变量和模块 patch 比手动 `unittest.mock` 简洁
3. pytest 的参数化（`@pytest.mark.parametrize`）写法更直观
4. 错误信息更详细，assert 失败时显示具体值

unittest 完全够用，但 pytest 的开发体验更好。

---

**Q20：CI/CD 是怎么做的？**

**A：**
目前没有 CI（GitHub Actions 等），本地运行 `pytest` 是唯一的 gate。这是个人项目的务实选择——搭 CI 需要管理 secrets（API keys），对个人项目来说不划算。

如果要搭，方案是：
1. `pytest` 全量跑（mock LLM，无需 API key）
2. `ruff` check（已在 pyproject.toml 配置）
3. `mypy` 类型检查
4. PR 合并前必须通过

---

### 📌 F. 技术选型

---

**Q21：为什么选 typer 做 CLI 框架？**

**A：**
typer 基于 FastAPI 的设计理念，用 Python 类型注解自动生成 CLI 参数解析和帮助文档。对比：
- `argparse`：太底层，需要大量样板代码
- `click`：typer 的底层，typer 是 click 的类型注解友好封装
- `typer`：写 `def commit(mode: str = typer.Option(...))` 就自动有 `--mode` 参数和 help 文本，开发效率高

typer 还内置了 sub-app 支持（`skill_app = typer.Typer()`），让 `gitsage skill list/add/show/edit` 这样的命令组织很自然。

---

**Q22：为什么选 Rich？**

**A：**
Rich 是 Python 终端 UI 的事实标准库，提供：
- 彩色输出、Markdown 渲染、Syntax Highlight（展示 CTX.md 内容时用）
- Panel、Table、Progress、Status spinner 等组件
- `console.input()` 方法正确处理宽字符（解决了中文 prompt 下 backspace 位移的 bug）

alternative 是 `curses` 或 `blessed`，但 Rich 的 API 更高层、文档更好。

---

**Q23：为什么用 hatchling 打包而不是 setuptools？**

**A：**
hatchling 是现代 Python 打包工具，配置全在 `pyproject.toml`（PEP 517/518），不需要 `setup.py`。比 setuptools 配置更简单，构建速度更快，和 `uv`（现代包管理器）兼容性好。

---

### 📌 G. 挑战与难点

---

**Q24：开发过程中遇到的最大挑战是什么？**

**A：**
有几个印象深刻的：

**1. 语言强制覆盖问题**
用户设置了中文偏好，但 CTX.md 里有英文规范，LLM 产生了矛盾行为。花了一些时间才意识到 prompt 顺序的重要性——把用户偏好放到 system prompt 最顶部并加强措辞后才稳定解决。这让我理解了 LLM 对 prompt 位置的敏感性。

**2. 中文 prompt 下 backspace 失效**
用 `input("调整（空行跳过）> ")` 时，prompt 里有中文，用户按 backspace 删字符时终端显示异常（残留字符）。根因是 Python 的 readline 按字节数计算光标宽度，不了解中文字符实际占 2 列。修法是改用 `console.input()`，让 Rich 渲染 prompt 部分（Rich 正确处理宽字符），只让 readline 处理用户实际输入的部分。

**3. CTX.md 修改 prompt 和输出模型不对齐**
config init 的 CTX.md 修改功能，system prompt 说"只输出 CTX.md 内容"，但代码用 `StandupOutput` 模型（要求 JSON 格式），两条指令矛盾，LLM 输出了空内容。排查了一段时间，最后改成 prompt 明确要求输出 `{"content": "...", "items": []}` JSON 格式，和 output model 对齐。

> **追问：这几个问题是怎么发现的？靠测试还是实际使用？**
>
> 都是实际使用时发现的，不是测试发现的。测试用 mock LLM，覆盖不到 LLM 行为相关的问题；prompt 位置、宽字符这类问题需要真实运行才能暴露。这也是单元测试的局限性——mock 掉 LLM 之后，和真实 LLM 交互的边界就成了盲区。

---

**Q25：记忆系统的并发问题是怎么处理的？**

**A：**
MemoryManager 用文件系统存储（单个 Markdown 文件），守护线程异步写入。当前没有用锁，因为：
1. 写操作很简单：追加一行，整体覆盖
2. 实际使用中极少有两个 gitsage 进程同时写入同一个 repo 的记忆文件
3. 即使发生写冲突，丢失一条观测记录是可以接受的（best-effort 设计）

如果要做更严谨的并发控制，可以用 `filelock` 库做文件锁，或者改用 SQLite（自带事务）。

---

**Q26：如何处理 GitHub API 不可用的情况？**

**A：**
`explain` 命令有明确的降级策略：

1. 没有配置 GitHub Token → 跳过 PR/Issue API 调用，纯本地 git 历史分析，输出时注明"本地模式，置信度受限"
2. GitHub API 调用失败（网络超时、API 限速）→ 捕获异常，跳过这一步，继续用已有信息生成报告
3. 置信度字段在输出中明确标注（high/medium/low），让用户知道结果的可信程度

---

### 📌 H. 评测与指标

---

**Q27：你是怎么评测 gitsage 的？**

**A：**
做了两个评测：

**Study 1：LLM-as-Judge 质量评分**
- 数据集：encode/httpx 公开仓库的 10 条真实 commit（取 diff + 人类写的 message）
- 流程：对每个 diff 用 gitsage 生成候选，然后用同一 LLM 作为评委，对人类 message 和 gitsage message 独立打分（clarity / accuracy / overall 1-5）
- 结果：gitsage 4.8/5，人类基准 3.7/5

**Study 2：CTX.md 消融实验**
- 数据集：gitsage 仓库近 19 条真实 commit
- 流程：同一 diff 分别用"无 CTX.md"和"有 CTX.md"生成 commit message，用正则检测是否符合 Conventional Commits 格式 + 检测描述部分是否为中文
- 结果：CC 合规率两者均 100%（说明基础模型已够强），语言一致性：无 CTX.md 时 0% 中文（LLM 默认英文），有 CTX.md 时 100% 中文

> **追问：你这个评测有什么局限性？**
>
> 局限性我很清楚，主要三个：
> 1. **n 太小**：Study 1 只有 10 条，来自一个仓库，样本有偏差
> 2. **自评偏差**：生成模型和评委是同一个（deepseek-v4-flash），模型可能对自己的输出偏爱
> 3. **baseline 质量参差**：encode/httpx 的 commit message 本身质量不均（有些很随意），不是严格意义上的"人类优质基准"
>
> 更严谨的做法是：用独立模型（比如 Claude）评 DeepSeek 的输出，n 扩到 100+，覆盖 5 个以上不同风格的仓库，做统计显著性检验。目前的数据只能作为初步验证，不适合做强声明。

> **追问：那 Study 1 的结果（4.8 vs 3.7）还算不算数？**
>
> 方向上有参考价值，具体数字不应该过度引用。有意思的规律是：encode/httpx 开发者有时写很随意的 message（"Update dependencies"），而 gitsage 总是输出结构化的 CC 格式（"chore(deps): update trio from 0.30.0 to 0.31.0"），评委给后者更高分是自然的。但这说明的是 gitsage 在 CC 规范上更一致，不一定代表总体质量更高。

---

### 📌 I. 扩展性与未来规划

---

**Q28：如何扩展一个新的命令？**

**A：**
标准流程：
1. 在 `context/builder.py` 加 `build_xxx_context()` 方法，定义该命令需要的上下文
2. 在 `agent/prompts.py` 加 system prompt 和 user prompt builder
3. 在 `agent/models.py` 加输出的 Pydantic 模型
4. 在 `cli.py` 里加 `@app.command()` 函数，串联 context → prompt → llm → harness → output
5. 加对应测试

整个过程遵循同一套模式，新增命令不需要修改已有代码。

---

**Q29：如果要支持一个新的 LLM provider 怎么做？**

**A：**
1. 在 `agent/llm.py` 里创建新的 `XxxClient` 类，继承 `BaseLLMClient`，实现 `complete()` 方法
2. 在 `create_llm_client()` 工厂函数里加对应的 `if provider == "xxx"` 分支
3. 不需要改其他任何代码——所有上层代码依赖 `BaseLLMClient` 接口

---

**Q30：你觉得这个项目最大的不足是什么？如果再做一次会改什么？**

**A：**
几个我认为真实的不足：

1. **没有集成测试**：单元测试覆盖好，但 LLM 行为相关的边界没有测试，只能靠人工使用发现
2. **diff 处理太简单**：超长 diff 简单截断，更好的做法是语义压缩或 chunk 处理
3. **Study 1 评测方法论有缺陷**：样本量小 + 自评偏差，如果要放简历上应该做更严谨的评测
4. **config init 的 CTX.md 草稿质量不稳定**：对 commit 历史少或质量差的仓库，生成的 CTX.md 效果一般
5. **没有 Web UI**：对于不习惯终端的用户不友好（但这是设计取舍，不是 bug）

如果重新设计，我会从一开始就设计评测 pipeline，每次功能迭代都跑评测，而不是最后补做。

---

### 📌 J. 行为类 (BQ)

---

**Q31：这个项目你最有成就感的部分是什么？**

**A：**
有两个部分：

一是 **`explain` 迭代式 Agent** 的实现。这是我第一次从零设计一个真正的 agent loop——模型不是执行固定流程，而是自主决策要获取什么信息。调通第一次完整运行时，看到模型先读 blame、发现一个可疑 commit、自动去拉 PR 详情、最后输出带 citation 的分析，有一种"这才是 AI 应该有的样子"的感觉。

二是 **整体的工程完整性**。这不是一个 demo，它有 200+ 测试、有 CHANGELOG、发布到 PyPI 全球可安装、有 MCP 集成。一个人从零做到这个程度，对自己来说是一次完整的产品交付体验。

---

**Q32：这个项目有没有真实用户？**

**A：**
目前主要是我自己日常使用。commit / standup 两个命令是每天都在用的，confirm 过它在真实工作场景里有价值。PyPI 发布后有一些下载量，但没有跟踪具体用户反馈。

这也是我认为下一阶段最重要的事：找几个开发者真实使用，收集反馈，而不是在没有用户数据的情况下继续堆功能。

---

**Q33：一个人做这么大的项目，怎么控制范围避免失控？**

**A：**
主要靠两件事：
1. **明确 MVP 边界**：先把 commit / standup 两个核心命令做到能用，再扩展 PR / explain / catchup，再做 MCP / memory / skill
2. **写设计文档（docs/design.md）在动手前**：把所有命令的接口、UX 样例、架构决策都提前写清楚，实际开发时遵循设计而不是边写边想

仍然有范围蔓延的问题（比如加了 config init 的交互式修改循环），但因为有设计文档作为 anchor，不会完全失控。

---

**Q34：这个项目让你对 LLM 工程有什么新的认识？**

**A：**
几个之前没意识到的事：

1. **Prompt 位置比 Prompt 内容更重要**：同样的指令放在 system prompt 顶部和底部，效果差异显著
2. **确定性控制不能完全依赖 LLM**：对于"必须有 ticket 号"这类规则，不管 prompt 写得多清楚，总有一定概率 LLM 忽略，代码层面的强制执行不可少
3. **结构化输出是生产可用的前提**：让 LLM 输出自由文本然后解析，在 demo 里可以，在真实系统里太脆弱，Pydantic + structured output 是正解
4. **评测比开发更难**：写代码有确定答案，评测 LLM 输出质量没有确定答案，需要专门设计 methodology

---

### 📌 K. 压力追问 / 刁钻问题

---

**Q35：你说 gitsage 质量超越了人类基准，这个说法是不是有点夸大？**

**A：**
是的，这个说法过于夸大了，我在介绍时会避免这样表述。

实际情况：在那个评测里（encode/httpx 仓库，10 条样本），encode/httpx 的开发者有时写了比较随意的 commit message（"Update dependencies"），gitsage 则始终输出 Conventional Commits 格式，结构更规范，所以 LLM 评委给了更高分。但这说明的是 gitsage 在"格式一致性"上优于那个仓库的人类习惯，不代表 AI 整体超越了人类写 commit 的能力。

同时评测本身有方法论缺陷：样本量小（n=10）、自评偏差（同一模型生成和评判）。更严谨的结论是"在有限样本上，gitsage 输出的格式规范性更强"，而不是"质量超越人类"。

---

**Q36：如果有用户反馈 gitsage 生成的 commit message 不准确，你怎么排查？**

**A：**
排查思路：
1. **看 diff 是否被截断**：如果 diff 很大，超出阈值被截断，LLM 只看到了部分变更
2. **看 CTX.md 是否正确加载**：用 `gitsage config show` 查看当前配置，确认 CTX.md 规范有没有正确解析
3. **看 Memory 内容**：用 `gitsage memory show` 看记忆内容，确认没有错误的历史数据干扰
4. **用 `--estimate` 看 token 分布**：了解 prompt 里各部分的大小
5. **最终看 prompt**：在代码里临时加日志打印完整 prompt 和 LLM 原始输出，直接看是哪里出了问题

---

**Q37：这个项目的数据安全怎么保证？diff 会不会被上传到你自己的服务器？**

**A：**
不会。gitsage 是纯本地的工具，数据直接从用户的 terminal 发送到用户配置的 LLM API（OpenAI、Anthropic、DeepSeek、或本地 Ollama），不经过任何中间服务器。

首次运行有显式的隐私 consent 流程，明确告知用户哪些数据会发送给哪个 API。用户可以完全选择本地 Ollama 模式，数据完全不出本机。这个设计是刻意的，目的是让用户对数据流向有完整控制权。

---

**Q38：这个项目如果要支持 10 万用户并发使用，架构需要改什么？**

**A：**
目前架构是纯本地的，每个用户在自己机器上运行，天然支持"并发"——不同用户之间完全隔离，没有共享状态。

如果要做 SaaS（多用户共享服务端）：
1. LLM 调用层需要添加 per-user rate limiting 和 cost tracking
2. 记忆系统从本地文件改为数据库（PostgreSQL / Redis）
3. CTX.md 和 Skills 需要多租户隔离（user_id + repo_id 作为 namespace key）
4. MCP Server 从 stdio 改为 HTTP SSE，支持多个并发客户端连接
5. 加认证层（OAuth / API Token）

但这会从"开发者自托管工具"变成"云服务产品"，是不同的产品定位，需要重新考量商业模式。

---

**Q39：你做这个项目学到的最重要的一件事是什么？**

**A：**
"确定性控制不能依赖 LLM 的自觉性。"

在项目早期，我以为只要 prompt 写得足够清楚，LLM 就会按规范输出。但实际使用中发现，就算 prompt 里写了"必须用中文"、"必须包含 JIRA ticket"，LLM 总有一定概率忽略。

这让我理解了为什么工业级 LLM 应用不能只依赖 prompt——必须在代码层面做强制验证和规则执行，把"这件事 AI 可能做错"变成"这件事代码保证它对"。这也是 Harness 层存在的核心原因，也是我认为这个项目里最有工程价值的设计决策。

---

## 五、你可以主动问面试官的问题

1. 贵司目前 LLM 应用的主要痛点是什么——输出质量不稳定，还是工程化程度不够？
2. 对于 AI 工具类项目，贵司更看重快速迭代的速度，还是系统的可维护性和测试覆盖？
3. 团队目前有在用 MCP 或者类似的 AI 工具集成协议吗？
4. 评测 AI 输出质量这块，贵司有成熟的 pipeline 吗，还是还在探索阶段？

---

*最后更新：2026-06-24*
