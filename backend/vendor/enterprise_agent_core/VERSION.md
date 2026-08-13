# Enterprise Agent Core vendor snapshot

- Core version: `0.1.0`
- Source: `/Users/libaodian/Desktop/初号机agent/enterprise-agent-framework`
- Copied on: `2026-08-13`
- Scope: `src/enterprise_agent/` Python source plus the Core dependency manifests.
- Excluded: virtual environments, bytecode caches, evaluation reports, runtime data, and example tenant Packages.
- Source tree digest (SHA-256 of the sorted per-file SHA-256 manifest): `26be18b1ff5b7351447f76534e63a4ddc7bb69a03fc24d01774954489c44502e`

## 本地补丁记录

本节记录相对上游 `0.1.0` 的所有 Core 变更。当前 SHA-256
`26be18b1ff5b7351447f76534e63a4ddc7bb69a03fc24d01774954489c44502e`
校验的是“上游 `0.1.0` + 以下本地补丁”，不是未修改的上游源码。

| 日期 | 文件 | 改动内容 | 原因 |
| --- | --- | --- | --- |
| 2026-08-13 | `src/enterprise_agent/contracts/tool.py` | `ToolSpec` 新增受限的 `timeout_seconds` 字段。 | SteelDigitize 的 12 个本地 ToolSpec 需显式声明超时预算；字段为通用引擎契约，不含客户业务逻辑。 |
| 2026-08-13 | `src/enterprise_agent/harness/tools/executor.py`、`src/enterprise_agent/harness/tools/__init__.py` | 新增并导出 `ToolExecutionDenied`、`ToolExecutionFailed`；Executor 分别归一为 DENIED 与 FAILED ToolResult。 | 本地 handler 在执行上下文校验后需要表达事实拒绝（如跨会话 scope 缺失）和既有业务函数的事实失败，不能把它们误记为成功证据。 |
| 2026-08-13 | `src/enterprise_agent/harness/persistence/sqlite.py` | 新增只读 `list_pending_approvals()`，按持久化的 pending 决策稳定排序返回 `ApprovalRecord`。 | 宿主需要在后端重启后列出可恢复的审批；方法只暴露通用契约，参数脱敏仍由宿主展示层负责。 |
| 2026-08-13 | `src/enterprise_agent/contracts/state.py`、`harness/context/assembler.py`、`harness/runtime/loop.py`、`orchestration/langgraph/runtime.py`、`api.py` | 新增可选的渐进式 Skill 披露模式：系统级 `select_skill` 虚拟工具以 Package 声明的 Skill ID 枚举校验选择；选择后展开该 Skill 的完整 metadata 与指令，并以它与 policy 交集的工具面替换当前业务工具面。未选择时不暴露业务工具；选择器不进入业务 ToolRegistry、不触发审批。 | 将“按需展开能力、最小上下文、工具面不可累积”的机制沉入通用引擎；宿主只提供 Package，Harness 仍强制 schema、policy 与审批。 |

这四项通用引擎改进将在 SteelDigitize 试点完成后回流初号机上游；当前仅以该记录和
哈希保证试点 vendor 的可审计性。

To reproduce the digest from the repository root:

```sh
find backend/vendor/enterprise_agent_core/src -type f -name '*.py' -print0 \
  | sort -z | xargs -0 shasum -a 256 \
  | shasum -a 256
```
