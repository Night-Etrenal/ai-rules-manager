# AI Rules Manager

AI Rules Manager 是一个面向 AI 编程代理的确定性规则、上下文与工作流管理器。它把平台约束、安全策略、业务领域规则和长期任务状态编译成 Codex 可直接读取的 `AGENTS.md`、仓库级 Skill 与可审计的生命周期 hooks。

当前首版聚焦：

- Debian 12/13 开发与运维环境
- OpenAI Codex 的 `AGENTS.md`、`.agents/skills` 与 `.codex/hooks.json`
- 规则分层、优先级解析和冲突检测
- 长任务计划持久化、SHA-256 完整性校验和上下文恢复
- Codex 本地 SQLite/WAL 只读审计与显式离线保护
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

## Codex 本地写盘保护

开发过程中只执行只读采样，不结束会话、不 checkpoint、不修改 trigger：

```bash
rulesctl codex-io-audit
rulesctl codex-io-audit --samples 3 --interval 10
rulesctl codex-io-audit --details
rulesctl codex-io-audit --json
```

默认审计只采样文件大小和索引化的 `MAX(id)`；`--details` 才额外进行完整行数与 TRACE 统计，避免检测本身造成不必要的读取负载。

`codex-io-guard` 和 `codex-io-restore` 默认都是 dry-run。只有显式传入 `--apply`，并且检测不到任何 Codex/app-server 进程时，才允许离线修改：

```bash
# 先保存工作并完全退出 Codex
rulesctl codex-io-guard --apply

# 官方修复后或需要恢复诊断日志时
rulesctl codex-io-restore --apply
```

Guard 会先备份 `logs_2.sqlite`、WAL 和 SHM，执行完整性检查，再创建可逆的 INSERT 拦截 trigger 并 truncate WAL。正常的 `init`、`compile`、`audit`、计划和 hooks 流程永远不会触碰 `CODEX_HOME`。完整说明见 `docs/codex-local-io.md`。

## Context Mode

| 模式 | 生成的 hooks | 推荐场景 |
|---|---|---|
| `minimal` | `SessionStart`、`PreCompact` | 默认；最低额外 I/O 与 Token 成本 |
| `balanced` | minimal + `UserPromptSubmit` | 需要每轮刷新计划的多阶段开发 |
| `strict` | balanced + 非阻塞 `Stop` 提示 | 高风险部署、事故处理 |

所有生成 hook 的超时上限为 1 秒，计划上下文限制为 3,000 字符；hooks 不扫描 `CODEX_HOME`、不调用 SQLite、不启动后台任务，也不递归遍历仓库。

## 安全原则

1. `task_plan.md` 只保存可信目标、阶段和决策。
2. 网页、日志和第三方内容写入 `findings.md`，不得成为高优先级规则。
3. `rulesctl attest` 对当前计划写入 SHA-256；不匹配时 hooks 拒绝注入计划正文。
4. hooks 使用仓库根目录绝对解析，不信任当前子目录相对路径。
5. `PLANNING_DISABLED=1` 可为一次性 Codex 任务关闭所有计划 hooks。
6. 项目级 hooks 必须由用户在 Codex `/hooks` 中审查并信任。
7. Codex 内部数据库维护必须显式、离线、先备份后修改；正在开发时只允许只读观察。
8. 项目规则、任务规则和领域规则不能进入平台/安全保留优先级区间。

## 测试

```bash
python -m unittest discover -s tests -v
```

CI 在 Debian Bookworm 和 Debian Trixie 容器中执行安装、测试和 Python 编译检查。

## 状态

`0.1.0` 是可运行的独立 MVP。当前只承诺 Debian 与 Codex；Windows、Claude Code、Cursor、Kiro、Pi、OpenCode 等适配不在首版支持范围。Windows Codex Desktop 与 WSL 可能使用不同的 `CODEX_HOME`，且 WSL 内的 `/proc` 无法检测原生 Windows Codex 进程，因此离线 guard 在该场景下必须显式指定实际目录并人工确认所有 Windows 进程已经退出。
