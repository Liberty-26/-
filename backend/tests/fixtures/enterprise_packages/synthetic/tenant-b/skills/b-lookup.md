---
schema_version: "1.0"
skill_id: synthetic-b-lookup
version: "1.0.0"
name: Synthetic B Lookup
description: Controlled tenant B Tool fixture.
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
    tenant_id: {const: synthetic-b}
allowed_tools: [tenant_b_lookup]
validator: json_schema
synthetic: true
---

Use only `tenant_b_lookup` and its real ToolResult evidence. Cite the returned
`source_id`; never infer or request Synthetic A facts.
