---
schema_version: "1.0"
skill_id: receipt-export
version: "0.1.0"
name: 单据导出
description: 将选定单据从权威数据库导出到 Excel，写入须经审批。
input_contract:
  type: object
  additionalProperties: false
  required:
    - request
    - selected_ids
  properties:
    request:
      type: string
      minLength: 1
    selected_ids:
      type: array
      minItems: 1
      uniqueItems: true
      items:
        type: integer
    filepath:
      type: string
      minLength: 1
    sheet:
      type: string
      minLength: 1
    mode:
      type: string
      enum: [new, append]
output_contract:
  type: object
  additionalProperties: false
  required:
    - summary
    - exported_receipt_count
    - verified
  properties:
    summary:
      type: string
      minLength: 1
    exported_receipt_count:
      type: integer
      minimum: 0
    verified:
      type: boolean
    evidence_id:
      type: string
      minLength: 1
allowed_tools:
  - spreadsheet_export_receipts
validator: json_schema
synthetic: false
---

只可通过 spreadsheet_export_receipts 导出。将 selected_ids 或用户明确指定的单据 ID
交给工具；不得在参数中编造或转述品名、数量、单价或其他明细。该工具是写操作，必须
等待 Harness 审批；只有成功 ToolResult 及校验证据存在时才可以报告导出和验证成功。
最终输出必须满足 output_contract。
