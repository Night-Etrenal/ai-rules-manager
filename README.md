# AI Rules Manager

AI Rules Manager 是一个面向 AI 编程代理的确定性规则、上下文与工作流管理器。它把平台约束、安全策略、业务领域规则和长期任务状态编译成 Codex 可直接读取的 `AGENTS.md`、仓库级 Skill 与可审计的生命周期 hooks。

当前首版聚焦：

- Debian 12/13 开发与运维环境
- OpenAI Codex 的 `AGENTS.md`、`.agents/skills` 与 `.codex/hooks.json`
- 规则分层、优先级解析和冲突检测
- 长任务计划持久化、仓库外 HMAC-SHA256 完整性校验和结构化上下文恢复
- Codex 本地 SQLite/WAL 只读审计与显式实验性离线保护
- 符号链接/路径逃逸防护、原子写入和低 I/O 审计
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
rulesctl attest
```

首次 `rulesctl attest` 会在仓库外创建：

```text
~/.config/ai-rules-manager/attestation.key
```

密钥为 32 字节、权限必须是 `0600`。仓库内只保存 HMAC，不保存密钥。旧版裸 SHA-256 attestation 不再被 hook 信任，升级后重新执行 `rulesctl attest`。

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

`codex-io-guard` 和 `codex-io-restore` 默认都是 dry-run。SQLite trigger 是临时实验性缓解，不是 Codex 官方修复。只有完全退出 Codex，并同时提供三个明确参数后才会修改：

```bash
# 先保存工作并完全退出 Codex
rulesctl codex-io-guard \
  --apply \
  --experimental \
  --accept-diagnostic-loss

# 官方修复后或需要恢复诊断日志时
rulesctl codex-io-restore \
  --apply \
  --experimental \
  --accept-diagnostic-loss
```

维护操作会拒绝 NFS、SMB/CIFS、SSHFS、9p、DrvFS、`/mnt/c` 和带符号链接组件的 `CODEX_HOME`；使用排他锁并在备份前后多次检查 Codex 进程。默认单次备份上限 2 GiB、备份总量上限 8 GiB、最多 8 份，并预留 64 MiB 空间。需要把备份放到另一块本地磁盘时使用：

```bash
rulesctl codex-io-guard \
  --apply --experimental --accept-diagnostic-loss \
  --backup-dir /srv/local-backups/codex
```

正常的 `init`、`compile`、`audit`、计划和 hooks 流程永远不会触碰 `CODEX_HOME`。完整说明见 `docs/codex-local-io.md`。

## Context Mode

| 模式 | 生成的 hooks | 推荐场景 |
|---|---|---|
| `minimal` | `SessionStart`、`PreCompact` | 默认；最低额外 I/O 与 Token 成本 |
| `balanced` | minimal + `UserPromptSubmit` | 需要每轮刷新计划的多阶段开发 |
| `strict` | balanced + 非阻塞 `Stop` 提示 | 高风险部署、事故处理 |

所有生成 hook 的超时上限为 1 秒，计划上下文限制为 3,000 字符；hook 只注入经过 HMAC 校验的目标、阶段状态和决策 JSON，不注入完整 Markdown。hooks 不扫描 `CODEX_HOME`、不调用 SQLite、不启动后台任务，也不递归遍历仓库。

## 安全原则

1. `task_plan.md` 只保存可信目标、阶段和决策。
2. 网页、日志和第三方内容写入 `findings.md`，不得成为高优先级规则。
3. `rulesctl attest` 使用仓库外 0600 密钥计算 HMAC-SHA256；密钥缺失、权限错误或内容变化时 hooks 拒绝注入。
4. 所有生成文件使用防符号链接的原子写入；控制文件不能越过仓库根目录。
5. `PLANNING_DISABLED=1` 可为一次性 Codex 任务关闭所有计划 hooks。
6. 项目级 hooks 必须由用户在 Codex `/hooks` 中审查并信任。
7. Codex 内部数据库维护必须显式、实验性、离线、仅限本地文件系统，并先完成有容量上限的备份。
8. 项目规则、任务规则和领域规则不能进入平台/安全保留优先级区间。
9. 默认采用 `workspace-write` 与按需审批；不得默认启用 `danger-full-access`。
10. 批量删除、`rm -rf`、`git clean -fdx` 和 `git reset --hard` 必须提供规范化目标清单并获得执行时确认。

## 测试

```bash
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m compileall -q src tests
```

CI 在固定 digest 的 Debian Bookworm 和 Debian Trixie 容器中执行安装、测试和 Python 编译检查，`actions/checkout` 固定到完整 commit SHA。

## 状态

`0.1.0` 是可运行的独立 MVP。当前只承诺 Debian 与 Codex；Windows、Claude Code、Cursor、Kiro、Pi、OpenCode 等适配不在首版支持范围。Windows Codex Desktop 与 WSL 可能使用不同的 `CODEX_HOME`，且 WSL 内的 `/proc` 无法检测原生 Windows Codex 进程，因此本工具会拒绝对 `/mnt/c` 等 Windows 挂载执行维护。Codex 自身的 TRACE 日志、进程泄漏、工作区清理或沙箱缺陷只能由 OpenAI 修复，本仓库只能检测、隔离和降低影响。
