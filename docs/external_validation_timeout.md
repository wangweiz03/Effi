# External Validation Timeout Contract

## Status

Implemented design target. Runtime control uses one framework-owned external validation timeout per round.

All accounting uses actual sandbox runtime. Wall time and token use are audit signals only.

## Single-Layer Authority

The scheduler computes one authoritative value before coding:

```text
validation_timeout_seconds
```

This value is the external sandbox wall-clock cap for the validation job. It is not a prepaid cost, an estimate of expected runtime, or a request that the generated solution must consume.

The coding prompt displays the cap as read-only context. Codex does not request a different timeout in `context_readiness.md`, and the runner does not parse, clamp, or align a post-readiness budget.

## Framework Allocation

The framework takes the smaller of remaining task-level sandbox runtime and a deliberately generous workload-profile cap:

- low-cost: `3600s`;
- sparse text: `7200s`;
- general: `10800s`;
- deep media: `10800s`.

Normal branch scheduling is method-neutral because the coding agent chooses the concrete route only after reading context. It therefore uses the general `10800s` cap. Callers that already have a concrete operator may select a lower low-cost or sparse cap. Branch state, historical runtimes, and prior timeout saturation do not tighten this external wall, including for timeout recovery.

A larger cap only permits the job to run longer; it does not consume time unless the sandbox process actually runs for that duration. Failed and timed-out rounds remain routing evidence, not timeout-allocation inputs.

## Prompt Contract

PART 3 renders a compact `[EXTERNAL VALIDATION TIMEOUT]` block containing:

- remaining task-level sandbox runtime;
- the authoritative external validation timeout;
- a reminder that only actual sandbox runtime is charged.

The block is informational and read-only. It must not ask Codex to choose, negotiate, or repeat the timeout in a JSON plan. Static execution rules remain in PART 1 and are not duplicated in PART 3.

`context_readiness.md` records evidence acquisition and the intended implementation, validation, fallback, and failure traps. It does not participate in timeout selection.

## Solution Runtime Responsibility

`solution.py` must be statically bounded even though the external cap is generous. A robust solution should:

- bound folds, epochs, candidates, features, resolution, decoding, and search width;
- complete a competitive trained score-first path before optional expensive tiers;
- keep the current best prediction in memory once a candidate is complete;
- skip optional work when its completion is doubtful;
- write a schema-valid `submission.csv` atomically and exit normally;
- avoid relying on a partially written file surviving an external kill.

The framework does not rewrite solution constants to match the external timeout. Solutions must not mirror the timeout or implement local timers, deadline guards, remaining-time polling, or budget exceptions; workload size is controlled statically instead.

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
3. readiness remains an evidence and implementation-planning artifact;
4. generated code does not alter the frozen timeout;
5. early exit consumes only actual sandbox runtime;
6. explicit runtime exhaustion routes to timeout recovery;
7. ordinary exceptions containing timeout configuration text route to repair failure;
8. zero-output sandbox timeouts remain auditable without claiming a method-specific cause.

Full evaluator smoke tests require the external sandbox and inference services.
