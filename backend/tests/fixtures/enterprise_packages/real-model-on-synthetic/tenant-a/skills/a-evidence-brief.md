---
schema_version: "1.0"
skill_id: real-synthetic-a-evidence-brief
version: "1.0.0"
name: Real Model Synthetic A Evidence Brief
description: Real-model evidence brief over controlled Synthetic A facts.
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
  required: [status, brief]
  properties:
    status: {enum: [grounded, refused]}
    brief: {type: string, minLength: 1}
    fact_id: {type: string, minLength: 1}
    source_id: {type: string, minLength: 1}
    tenant_id: {const: real-model-synthetic-a}
  allOf:
    - if:
        properties: {status: {const: grounded}}
      then:
        required: [fact_id, source_id, tenant_id]
allowed_tools: [tenant_a_lookup]
validator: json_schema
synthetic: true
---

This is a real-model evaluation over controlled synthetic facts. Call only
`tenant_a_lookup` with the exact input `fact_id`. Build `brief` only from its successful
ToolResult and copy the exact evidence identifiers. Refuse facts from other tenants and
never invent or cross-load them.
