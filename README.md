# AI Rules Manager

AI Rules Manager 是一个面向 AI 编程代理的确定性规则、上下文与工作流管理器。它把平台约束、安全策略、业务领域规则和长期任务状态编译成 Codex 可直接读取的 `AGENTS.md`、仓库级 Skill 与可审计的生命周期 hooks。

当前首版聚焦：

- Debian 12/13 开发与运维环境
- OpenAI Codex 的 `AGENTS.md`、`.agents/skills` 与 `.codex/hooks.json`
- 规则分层、优先级解析和冲突检测
- 长任务计划持久化、SHA-256 完整性校验和上下文恢复
- 零运行时第三方依赖，Python 3.11+

## 为什么不是简单复刻

本仓库最初基于 `OthmanAdi/planning-with-files` 的 MIT 许可思想与部分机制进行研究。当前版本已经重构为独立架构：使用 TOML 规则注册表、规则编译器、冲突解析、安全审计、Codex 官方目录结构和独立 CLI。上游归属与许可说明见 `NOTICE.md` 和 `UPSTREAM.md`。

## 核心模型

```text
安全规则 > 平台规则 > 全局规则 > 领域规则 > 项目规则 > 当前任务规则
```

同一 `key` 出现不同 `value` 时，优先级更高的规则生效；系统同时报告被遮蔽规则，避免静默冲突。

## 快速开始

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

rulesctl init \
  --name example-project \
  --platform debian \
  --domain infrastructure \
  --context-mode minimal

rulesctl validate
rulesctl compile
rulesctl audit
```

生成内容：

```text
.ai-rules-manager.toml
AGENTS.md
.agents/skills/ai-rules-manager/SKILL.md
.codex/hooks.json
.codex/hooks/*.py
.ai-rules/manifest.json
.planning/<date>-initial-task/
```

## 常用命令

```bash
rulesctl list-rules
rulesctl validate
rulesctl compile --target all
rulesctl audit
rulesctl plan-init "Deploy service"
rulesctl plan-status
rulesctl attest
rulesctl attest --show
rulesctl attest --clear
```

## Context Mode

| 模式 | 行为 | 推荐场景 |
|---|---|---|
| `minimal` | 会话启动和上下文恢复时注入计划摘要 | 默认；控制 Token 成本 |
| `balanced` | 在 `minimal` 基础上，每次用户提交时刷新摘要 | 多阶段开发 |
| `strict` | 在 `balanced` 基础上，结束前检查未完成阶段 | 高风险部署、事故处理 |

首版不会自动阻塞 Codex 停止，也不会自动执行部署命令。hooks 只读取本仓库内已验证的状态文件并返回提示。

## 安全原则

1. `task_plan.md` 只保存可信目标、阶段和决策。
2. 网页、日志和第三方内容写入 `findings.md`，不得成为高优先级规则。
3. `rulesctl attest` 对当前计划写入 SHA-256；不匹配时 hooks 拒绝注入计划正文。
4. hooks 使用仓库根目录绝对解析，不信任当前子目录相对路径。
5. `PLANNING_DISABLED=1` 可为一次性 Codex 任务关闭所有计划 hooks。
6. 项目级 hooks 必须由用户在 Codex `/hooks` 中审查并信任。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 状态

`0.1.0` 是可运行的独立 MVP。当前只承诺 Debian 与 Codex；Windows、Claude Code、Cursor、Kiro、Pi、OpenCode 等适配不在首版支持范围。
