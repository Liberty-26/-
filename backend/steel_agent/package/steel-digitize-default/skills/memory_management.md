---
schema_version: "1.0"
skill_id: memory-management
version: "0.1.0"
name: 长期记忆管理
description: 读取或以版本比较并交换方式更新 Agent 长期记忆。
input_contract:
  type: object
  additionalProperties: false
  required:
    - request
  properties:
    request:
      type: string
      minLength: 1
    proposed_content:
      type: string
      minLength: 1
    expected_revision:
      type: integer
      minimum: 0
output_contract:
  type: object
  additionalProperties: false
  required:
    - summary
  properties:
    summary:
      type: string
      minLength: 1
    revision:
      type: integer
      minimum: 0
    changed:
      type: boolean
    evidence_id:
      type: string
      minLength: 1
allowed_tools:
  - memory_list
  - memory_replace
validator: json_schema
synthetic: false
---

更新前必须先用 memory_list 读取当前 revision；仅在提交的 expected_revision 与当前版本
一致时才请求 memory_replace。修改是写操作，必须等待 Harness 审批。版本冲突、拒绝或
失败是事实，不得声称记忆已更新。最终输出必须满足 output_contract。
