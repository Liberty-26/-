# SteelDigitize Default Agent Package

这是 SteelDigitize 的本地默认 Package（`steel-digitize-default`），由初号机 Core
加载并通过既有的数据库、Excel、会话和 Memory 原语实现业务能力。

## 能力

- 查询单据和明细；
- 从权威数据库导出选定单据到 Excel；
- 查询本地工作目录、当前时间和受权限约束的会话历史；
- 读取或以 revision CAS 更新长期记忆。

## 重要边界

- Package 不含 API Key、客户数据或知识库内容；模型配置仅引用 `AGENT_API_*` 环境变量。
- 模型不得访问 Excel 底层原语；唯一 Excel 写入口为
  `spreadsheet_export_receipts`，它从数据库读取权威明细。
- Memory 与 Excel 写操作都需要 Core Policy 审批。工具的成功事实、证据和 Schema
  验证优先于模型文字。
- `session_id=all` 是否允许由执行时 scope 决定，Package 不授予跨会话权限。
- 缺失的 `WORK_DIR` 是事实失败，不能自动创建目录。

## 数据外发

真实模型调用会把当前任务输入、当前 Skill 指令和该 Skill 暴露的 Tool Schema 发送到
由 `AGENT_API_BASE` 指定的兼容服务。调用前需另行确认模型端点、数据范围与授权；P1
验证仅使用 Fake Model，不发送任何数据。

## 回退

该 Package 的首个版本是 `0.1.0`。运行入口由 `STEEL_USE_NEW_AGENT` Feature Flag 控制；
清空该变量并重启即可回到保留的旧 Agent Loop。
