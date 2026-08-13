---
schema_version: "1.0"
skill_id: receipt-query
version: "0.1.0"
name: 单据查询
description: 查询单据及其权威明细，不执行写操作。
input_contract:
  type: object
  additionalProperties: false
  required:
    - query
  properties:
    query:
      type: string
      minLength: 1
    selected_ids:
      type: array
      items:
        type: integer
      uniqueItems: true
output_contract:
  type: object
  additionalProperties: false
  required:
    - summary
    - receipt_count
  properties:
    summary:
      type: string
      minLength: 1
    receipt_count:
      type: integer
      minimum: 0
    receipts:
      type: array
      items:
        type: object
allowed_tools:
  - db_lookup_receipt
  - db_get_receipt_items
validator: json_schema
synthetic: false
---

根据用户的查询意图和已选单据进行单据查询。需要单据事实时，仅使用可用工具的真实
返回值；明细查询必须使用单据 ID。没有结果、工具拒绝或工具失败均应如实表达，不能把
模型推测写成数据库事实。最终输出必须满足 output_contract。
