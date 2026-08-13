# Evaluation assets

These assets implement evidence-first testing, evaluation, verification, and validation
for the generic framework. Every bundled tenant, Package, Skill, Tool, input, and output
is explicitly synthetic. Nothing here is a customer result or production claim.

## Assets

- `schemas/run_record.schema.json`: versioned automatic-scoring input contract.
- `datasets/core_cases.json`: seven deterministic framework cases and assertions.
- `datasets/synthetic_tenants.json`: two controlled A/B tenants and four test Skills.
- `datasets/real_model_ab_cases.json`: six real-model cases, each requiring three runs,
  over controlled synthetic A/B facts and bidirectional isolation probes.
- `datasets/real_model_ab_scoring_v2.json`: versioned, evidence-bound fact-atom rules
  for declared natural-language fields; strict structured fields remain unchanged.
- `schemas/real_model_ab_scoring_v2.schema.json`: V2 scoring-rule contract.
- `run_core_cases.py`: runs the deterministic cases with Fake Models and mock Tools.
- `run_real_model_ab.py`: strict DeepSeek V4 Flash smoke-then-full channel with no Fake
  fallback; emits `BLOCKED` when the authorized environment is absent or mismatched.
- `real_model_ab_scorer_v2.py`: offline re-scorer for preserved RunRecords; it calls no
  model or Tool and refuses to overwrite an existing report.
- `inspect_real_model_ab_partial.py`: read-only SQLite/JSONL inventory for interrupted
  runs. It emits an immutable `PARTIAL/INTERRUPTED/NOT_SCORED` manifest and never scores.
- `run_evaluation.py`: invokes no model or Tool; it scores existing RunRecord evidence.
- `preflight.py`: validates assets and reports deterministic/live-model readiness.

## Deterministic Framework Tests (not model evaluation)

```bash
.venv/bin/python evals/preflight.py
.venv/bin/python evals/run_core_cases.py
.venv/bin/python evals/run_evaluation.py \
  --records evals/reports/core_runs.jsonl \
  --report evals/reports/rescored_core_report.json
```

The deterministic framework suite uses `FakeModelAdapter` or scripted responders only.
Its PASS status proves framework control logic (state, policy, approval, persistence,
isolation enforcement, and scorer behavior); it does not prove Agent capability, model
capability, Skill adaptation, or customer outcome. Unauthorized execution, approval
bypass, cross-tenant leakage, external-action false success, or success without evidence
still forces this framework-test report to FAIL.

## Real-model evaluation

Real-model runs are a separate channel and are never inferred from deterministic tests.
They require an explicitly authorized OpenAI-compatible endpoint and a fresh secret
injected through environment variables. Each A/B case runs at least three times and
retains every model exchange, RunRecord, Tool trace, token/cost field, latency, and model
identifier. A missing or mismatched environment is `BLOCKED`, never `PASS`. Results are
reported as “real-model on synthetic fixtures”, never as real-customer acceptance.

### Natural-language scoring versions

The original `20260813_01` report used V1 exact-object scoring. That historical
`COMPLETE/FINAL/FAIL` result is preserved. A validity audit found that the failed
`real_ab_a_review_route` case differed only in its open natural-language `brief`; all
structured identity, source, evidence, and fact values were correct.

V2 scores declared prose fields with ToolResult-bound deterministic fact atoms while
keeping output shape, identity, source, tenant, status, resources, provider/model, and
evidence strict. It does not use fuzzy similarity, embeddings, or an LLM Judge. Re-score
existing evidence with:

```bash
.venv/bin/python -m evals.real_model_ab_scorer_v2 \
  --records evals/reports/real_model_ab_runs_20260813_01.jsonl \
  --original-report evals/reports/real_model_ab_report_20260813_01.json \
  --report evals/reports/real_model_ab_rescore_v2_<new-id>.json
```

The preserved V2 report is `reports/real_model_ab_rescore_v2_20260813_01.json` and is
explicitly labeled “同一真实输出、后续评分规则校正”. See
`reports/REAL_MODEL_AB_SCORER_V2_AUDIT_20260813_01.md` for the assertion audit.

## Interrupted run and resume

`--resume` is mandatory when records or the work directory already exist. The planner
indexes attempts by `(evaluation_case_id, evaluation_attempt)`, skips complete terminal
RunRecords, reconstructs a missing JSONL record from a terminal SQLite checkpoint, and
continues only genuinely missing/nonterminal attempts. Duplicate or incomplete existing
RunRecords block resume instead of being replaced.

The scorer has an independent completion gate: exactly all 18 structurally valid,
terminal real-model records must exist before final case PASS/FAIL is possible. An
incomplete set returns only `PARTIAL` (or `BLOCKED` for ambiguous evidence).

The `20260813_01` history is preserved at:

- `reports/real_model_ab_runs_20260813_01.jsonl`
- `reports/real_model_ab_work_20260813_01/`
- `reports/real_model_ab_partial_manifest_20260813_01.json`
- `reports/REAL_MODEL_EVIDENCE_INDEX_20260813_01.md`
- `reports/real_model_ab_report_20260813_01.json`
- `reports/REAL_MODEL_EVIDENCE_INDEX_20260813_01_FINAL_CLASSIFICATION.md`

Its facts must be separated by observation time:

- The interruption inspection snapshot remains
  `PARTIAL/INTERRUPTED/NOT_SCORED`; it is historical and does not contain a score.
- The original background process's final evidence set is `COMPLETE/FINAL`, with
  18/18 RunRecords and authoritative overall `FAIL` (5/6 cases passed). Completion time
  is the original report's `generated_at`, `2026-08-12T19:41:38.489032+00:00`.
- Resume/recovery validation is a separate deterministic framework result and neither
  replaces nor reruns the original model evidence.

The report was discovered after the partial snapshot had been classified. Discovery
timing is not grounds to reject a report whose inventory, summary, provider/model, and
timestamp reconcile with all 18 valid records. See:

- `reports/real_model_ab_late_arrival_status_20260813_01.json`
- `reports/REAL_MODEL_EVIDENCE_INDEX_20260813_01_LATE_ADDENDUM.md`
