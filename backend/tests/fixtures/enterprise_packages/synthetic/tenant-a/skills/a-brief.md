---
schema_version: "1.0"
skill_id: synthetic-a-brief
version: "1.0.0"
name: Synthetic A Brief
description: Controlled tenant A evidence brief fixture.
input_contract:
  type: object
  additionalProperties: false
  required: [request, fact_id]
  properties:
    request: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
output_contract:
  type: object
  additionalProperties: false
  required: [brief, fact_id, source_id, tenant_id]
  properties:
    brief: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
    source_id: {type: string, minLength: 1}
    tenant_id: {const: synthetic-a}
allowed_tools: [tenant_a_lookup]
validator: json_schema
synthetic: true
---

Use only `tenant_a_lookup`. Return a short evidence-grounded `brief` with the exact
`fact_id`, `source_id`, and tenant identifier from its successful ToolResult.
