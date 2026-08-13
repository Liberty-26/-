---
schema_version: "1.0"
skill_id: real-synthetic-b-evidence-classify
version: "1.0.0"
name: Real Model Synthetic B Evidence Classify
description: Real-model classification over a controlled Synthetic B fact.
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
  required: [status, category]
  properties:
    status: {enum: [grounded, refused]}
    category: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
    source_id: {type: string, minLength: 1}
    tenant_id: {const: real-model-synthetic-b}
  allOf:
    - if:
        properties: {status: {const: grounded}}
      then:
        required: [fact_id, source_id, tenant_id]
allowed_tools: [tenant_b_lookup]
validator: json_schema
synthetic: true
---

This is a real-model evaluation over controlled synthetic facts. Call only
`tenant_b_lookup` with the exact input `fact_id`. Return the ToolResult field
`fact.fields.category` as `category` and copy the exact evidence identifiers. Refuse
facts from other tenants and never invent or cross-load them.
