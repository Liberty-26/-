# SteelDigitize 初号机替换 P5 验收记录

日期：2026-08-13。所有真实模型请求仅包含本地合成单据 `R-DEMO-*`、合成明细或本机时间/目录事实；未读取或外发既有业务库内容。

## 双路径验收矩阵

| 类别 | 旧 Loop | 新 Core Bridge | 差异结论 |
| --- | --- | --- | --- |
| 单据查询 | 权威 SQLite 行 | 同一权威 SQLite 行 | 一致。 |
| 会话/上下文 | `session_id=all` 可直接检索 | 缺 `steel:session_all` 必须 DENIED；具备 scope 后可检索 | 新路径是有意的权限收紧，无越权。 |
| 设置/时间 | 读取本机事实 | 读取相同本机事实 | 一致。 |
| Excel | 缺失 WORK_DIR 事实失败且不建目录 | 相同事实失败且不建目录；实际写入额外先暂停审批 | 新路径增加审批，不放宽写入。 |
| Memory | 读取同一 revision 事实 | 读取同一 revision 事实，写入走 CAS + 审批 | 新路径增加并发与人工控制。 |
| Policy | 旧 Harness 允许进入写工具执行 | 新 Policy 先持久化 pending，再按原 thread/task/approval 恢复 | 新路径阻止未经批准写入。 |
| SSE/UI | stage/tool_call/tool_result/delta/done | 兼容上述事件，另支持 blocked 与安全审批摘要；错误由既有 bridge 回归覆盖 | 前端可用，无完整路径泄漏。 |
| 回退 | 未设 Flag 时旧 Loop 流式 mock 完整 done | `STEEL_USE_NEW_AGENT=1` 时新 Bridge 完整审批闭环 | Flag 移除立即回旧 Loop。 |

矩阵自动化：`backend/tests/test_steel_agent_p5_matrix.py` 8 项；与 P1–P4 测试合跑 30/30。Core 上游回归 58/58，前端生产构建通过。

## 真实模型冒烟

| 显式 Skill | 脱敏对话 | 结果 |
| --- | --- | --- |
| `receipt-query` | 查询 `R-DEMO-001` | 模型调用 `db_lookup_receipt`，输出命中状态与金额。 |
| `receipt-query` | 查询 `R-DEMO-NOT-FOUND` | 模型调用 `db_lookup_receipt`，如实输出无匹配。 |
| `receipt-export` | 导出选中的合成单据 | 模型调用 `spreadsheet_export_receipts`，正确进入 blocked；批准前零写入。 |

另一次 `workspace-context` 冒烟已调用 `runtime_now`，但第二次模型请求遭到提供方短暂失败；30 秒退避后的下一条真实模型查询恢复成功。该现象记录为提供方瞬态失败，不改变本地 Tool、Policy、审批或回退验收结论。

## 审批 UI 端到端

临时 SQLite 合成单据环境中，浏览器实际验证：

- 弹窗显示「导出对账单」、`approval.xlsx` 与「1 张单据」，不显示完整路径或明细；
- 拒绝后弹窗关闭、对话追加「已拒绝执行」、零写入；
- 批准后恢复原审批身份，恰好生成一次临时 Excel，待审批列表清空，前端显示完成结果。

## Skill 选择观察

当前实现是 `STEEL_AGENT_SKILL_ID` 显式选择，默认 `receipt-query`。真实模型在已选择 Skill 的允许工具范围内选择工具正确；Core 当前不会让模型在四个 Skill 间自动路由，因此上述冒烟不能证明“模型自动选择 Skill”。

建议老板在 P6 前拍板：保留显式选择（适合测试、后台工作流或 UI 卡片入口），或增加由模型基于四个 Skill 元数据作出的受控选择层；后者必须不使用中文关键词/正则，并保留输入契约、最小工具面和所有审批边界。

## P5.5 补充验收：Skill 渐进式披露

P5.5 已按方案拍板实施，替代上节“默认固定 `receipt-query`”的产品行为：未设置
`STEEL_AGENT_SKILL_ID` 时，Bridge 初始只向模型披露 4 个 Skill 的 `skill_id` 与 description；
模型须先调用系统级 `select_skill`。选择后才注入该 Skill 的完整 front matter 与 Markdown
指令，并以该 Skill 的 `allowed_tools ∩ policy.allow_tools` 替换业务工具面。选择器不是业务
ToolSpec，不进入业务 ToolRegistry，也不需要审批。设置 `STEEL_AGENT_SKILL_ID` 仍作为测试和
固定工作流开关，跳过该披露过程。

- 自动回归：`test_steel_agent_progressive_skills.py` 5/5；覆盖未选择时业务工具拒绝、导出
  Skill 的审批暂停、跨 Skill 切换收回旧工具面、伪造 Skill ID 的 Draft 2020-12 Schema 拒绝。
- 既有 P5 矩阵与 P1–P4 用例：30/30；Core 上游回归：58/58。
- 真实模型（仅本地合成 `R-DEMO-001` 与合成明细）：
  `select_skill(receipt-query) → db_lookup_receipt → db_get_receipt_items → success`；以及
  “先查询再导出”对话走到 `receipt-export`，`spreadsheet_export_receipts` 停在
  `waiting_approval`，未执行写入。
- 第一次查询的工具结果后续请求遇到提供方瞬态网络失败，按既有重试机制重跑成功；该失败未
  被归因于 Core、Policy 或业务工具。

Vendor `VERSION.md` 已登记该通用引擎补丁，且源码清单 SHA-256 为
`26be18b1ff5b7351447f76534e63a4ddc7bb69a03fc24d01774954489c44502e`。
