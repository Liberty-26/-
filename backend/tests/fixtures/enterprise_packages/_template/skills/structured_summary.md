---
schema_version: "1.0"
skill_id: structured-summary
version: "1.0.0"
name: Structured Summary
description: Produce one concise summary field from user-provided text.
input_contract:
  type: object
  additionalProperties: false
  required:
    - text
  properties:
    text:
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
allowed_tools: []
validator: json_schema
synthetic: true
---

Read only the material provided by the user. Return a concise summary in the required
`summary` field. Do not claim that any external query, message, write, or business action
has completed.
