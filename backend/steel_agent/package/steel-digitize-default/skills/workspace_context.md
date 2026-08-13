---
schema_version: "1.0"
skill_id: workspace-context
version: "0.1.0"
name: 工作区与会话上下文
description: 查询本机工作目录、当前时间和授权范围内的会话记录。
input_contract:
  type: object
  additionalProperties: false
  required:
    - request
  properties:
    request:
      type: string
      minLength: 1
    query:
      type: string
      minLength: 1
    session_id:
      type: string
      minLength: 1
output_contract:
  type: object
  additionalProperties: false
  required:
    - summary
  properties:
    summary:
      type: string
      minLength: 1
    work_dir_configured:
      type: boolean
    current_time:
      type: string
      minLength: 1
    match_count:
      type: integer
      minimum: 0
allowed_tools:
  - settings_read
  - runtime_now
  - session_search
validator: json_schema
synthetic: false
---

按问题需要查询真实的工作目录、当前时间或会话记录。默认仅检索当前会话；请求跨会话
检索时必须让 Harness 的 scope 校验决定是否允许。不得透露 API Key、完整敏感配置或未
授权会话内容。最终输出必须满足 output_contract。
