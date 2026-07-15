# External Validation Timeout Contract

## Status

Implemented design target. Runtime execution uses one framework-owned external validation timeout per round. Draft planning also has a prompt-visible soft workload ceiling, which is guidance rather than another timer.

All accounting uses actual sandbox runtime. Wall time and token use are audit signals only.

## Hard Execution Authority

The scheduler computes one authoritative value before coding:

```text
validation_timeout_seconds
```

This value is the external sandbox wall-clock cap for the validation job. It is not a prepaid cost, an estimate of expected runtime, or a request that the generated solution must consume.

The coding prompt displays the cap as read-only context. Codex does not request a different timeout in `context_readiness.md`, and the runner does not parse, clamp, or align a post-readiness execution budget.

This external cap is the only enforced runtime limit. The framework does not add a solution-local deadline, remaining-time poll, budget exception, or separate sandbox preflight.

## Framework Allocation

The framework takes the smaller of remaining task-level sandbox runtime and a deliberately generous workload-profile cap:

- low-cost: `3600s`;
- sparse text: `7200s`;
- general: `10800s`;
- deep media: `10800s`.

Normal branch scheduling is method-neutral because the coding agent chooses the concrete route only after reading context. It therefore uses the general `10800s` cap. Callers that already have a concrete operator may select a lower low-cost or sparse cap. Branch state, historical runtimes, and prior timeout saturation do not tighten this external wall, including for timeout recovery.

A larger cap only permits the job to run longer; it does not consume time unless the sandbox process actually runs for that duration. Failed and timed-out rounds remain routing evidence, not timeout-allocation inputs.

## Draft Planning Ceiling

Every draft receives a `3600s` soft planning ceiling. This ceiling is intentionally distinct from `validation_timeout_seconds`:

- it limits the planned complete workload, not the sandbox process;
- it is not a quota, target duration, or permission to fill an hour;
- a strong route whose evidence-backed expected runtime is five or ten minutes should still finish in five or ten minutes;
- the external cap remains available for ordinary runtime variance, startup cost, and imperfect estimates;
- crossing the soft ceiling does not create an internal kill path or alter timeout taxonomy.

The `3600s` value is calibrated from the old `test-lite` draft behavior: `92.6%` of the audited completed draft validations fit inside one hour. It therefore provides a broad envelope for complete competitive seeds without treating the slow tail as the normal design target.

The frozen branch decision contains structured `workload_plan_v1`. Draft readiness records these ordinary planning fields without copying that object:

- `draft_workload_ceiling_seconds`;
- `expected_complete_path_seconds`;
- `runtime_estimate_basis`;
- `dominant_cost_units`;
- `complete_workload_product`;
- `within_ceiling: yes`;
- `why_no_further_expansion`.

Historical runtime evidence must come from completed rounds of the same task and use actual sandbox runtime rather than configured timeout. A comparable successful route is strongest. A timeout is only a lower bound, and a failure before the dominant training or inference stage is not an end-to-end runtime estimate. Each cited record must identify round, branch, status, actual runtime, comparability, and the adjustment made for the new plan. When no comparable evidence exists, Codex must say so and estimate from explicit work units instead of inventing precision.

The draft soft ceiling does not become a universal non-draft limit. Debug estimates the repaired route from the failed parent and must reduce cumulative work when the failure is timeout or OOM. Improve estimates its change relative to the validation-best parent and preserves a complete incumbent path before optional work. Their decision-level `workload_plan_v1` has a null draft ceiling and carries bound-parent runtime evidence.

## Prompt Contract

PART 3 renders a compact `[EXTERNAL VALIDATION TIMEOUT]` block containing:

- remaining task-level sandbox runtime;
- the authoritative external validation timeout;
- a reminder that only actual sandbox runtime is charged.

The block is informational and read-only. It must not ask Codex to choose, negotiate, or repeat the external timeout as a workload-plan field. Static execution rules remain in PART 1 and are not duplicated in PART 3.

`context_readiness.md` records evidence acquisition and the intended implementation, validation, fallback, failure traps, and draft-only planning fields. It explains why the statically bounded workload is credible but does not participate in external timeout selection.

## Solution Runtime Responsibility

`solution.py` must be statically bounded even though the external cap is generous. A robust solution should:

- bound folds, epochs, candidates, features, resolution, decoding, and search width;
- complete a competitive trained score-first path before optional expensive tiers;
- keep the current best prediction in memory once a candidate is complete;
- skip optional work when its completion is doubtful;
- write a schema-valid `submission.csv` atomically and exit normally;
- avoid relying on a partially written file surviving an external kill.

The framework does not rewrite solution constants to match either ceiling. Solutions must not mirror the ceilings or implement local timers, deadline guards, remaining-time polling, or budget exceptions; workload size is controlled statically instead.

## Persistence

The frozen branch decision and round result persist the authoritative external timeout. `external_timeout_plan` also records the fixed policy, runtime profile, remaining sandbox runtime, and `framework_operator_cap` allocation basis for audit.

`rounds_summary.json` records actual sandbox runtime separately from the timeout cap. Task-level stopping and remaining-budget calculations use the actual runtime sum.

## Timeout Routing

Timeout recovery requires high-confidence evidence:

- an exact structured sandbox timeout status;
- an explicit runtime event such as `TimeoutError`, `timed out`, `deadline_guard`, or `BudgetExhausted`;
- a narrowly defined compatibility rule for legacy artifacts.

Variable names, configured timeout values, heartbeat identifiers, tensor dtypes, inference messages, and generic file extensions are not failure evidence. A zero-output external timeout should remain distinguishable from a code-observed runtime event so infrastructure stalls do not create unsupported method-level causal memory.

## Verification

Regression coverage should verify:

1. the scheduler always selects one positive external cap within remaining sandbox runtime;
2. the prompt displays that cap exactly once and as read-only context;
3. the frozen decision carries valid `workload_plan_v1`, while readiness remains an evidence and implementation-planning artifact;
4. generated code does not alter the frozen timeout;
5. early exit consumes only actual sandbox runtime;
6. explicit runtime exhaustion routes to timeout recovery;
7. ordinary exceptions containing timeout configuration text route to repair failure;
8. zero-output sandbox timeouts remain auditable without claiming a method-specific cause;
9. draft plans use `3600s` as a soft ceiling rather than a runtime quota;
10. no internal timer or separate sandbox preflight is introduced.

Full evaluator smoke tests require the external sandbox and inference services.
