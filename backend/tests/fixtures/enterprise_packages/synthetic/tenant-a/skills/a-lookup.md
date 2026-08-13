---
schema_version: "1.0"
skill_id: synthetic-a-lookup
version: "1.0.0"
name: Synthetic A Lookup
description: Controlled tenant A Tool fixture.
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
  required: [answer]
  properties:
    answer: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
    source_id: {type: string, minLength: 1}
    tenant_id: {const: synthetic-a}
allowed_tools: [tenant_a_lookup]
validator: json_schema
synthetic: true
---

Use only `tenant_a_lookup` and its real ToolResult evidence. Cite the returned
`source_id`; never infer or request Synthetic B facts.
