# CTX.md — gitsage 项目自身的上下文配置

## 项目背景
gitsage 是一个 git-native AI 开发者工作流助手，Python 实现。
核心模块：cli / config / context / agent / harness / skills / mcp

## Commit 规范
格式：<类型>(<模块>): <描述>
类型：feat / fix / refactor / test / docs / chore
语言：英文
示例：feat(cli): add interactive commit selection mode

## 规则
always:
  - commit message 使用英文
  - 描述简洁，动词开头
never:
  - 超过 72 字符
  - 包含文件路径
