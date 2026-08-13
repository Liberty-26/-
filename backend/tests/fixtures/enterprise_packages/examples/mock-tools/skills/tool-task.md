---
schema_version: "1.0"
skill_id: synthetic-tool-task
version: "1.0.0"
name: Synthetic Tool Task
description: Exercise read and write Tool lifecycle with no customer data.
input_contract:
  type: object
  additionalProperties: false
  required:
    - request
  properties:
    request:
      type: string
      minLength: 1
output_contract:
  type: object
  additionalProperties: false
  required:
    - answer
  properties:
    answer:
      type: string
      minLength: 1
allowed_tools:
  - synthetic_lookup
  - synthetic_write
validator: json_schema
synthetic: true
---

Use only the synthetic Tools exposed by the Harness when they are needed. Treat each
ToolResult status and evidence ID as authoritative. If a Tool is denied or fails, report
that fact and never claim the operation succeeded.
