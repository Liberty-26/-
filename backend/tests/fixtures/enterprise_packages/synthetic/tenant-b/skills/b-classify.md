---
schema_version: "1.0"
skill_id: synthetic-b-classify
version: "1.0.0"
name: Synthetic B Classify
description: Controlled tenant B evidence classification fixture.
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
  required: [category, fact_id, source_id, tenant_id]
  properties:
    category: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
    source_id: {type: string, minLength: 1}
    tenant_id: {const: synthetic-b}
allowed_tools: [tenant_b_lookup]
validator: json_schema
synthetic: true
---

Use only `tenant_b_lookup`. Return the evidence-backed `category` with the exact
`fact_id`, `source_id`, and tenant identifier from its successful ToolResult.
